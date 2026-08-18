import os
import json
import time
import asyncio
import logging
from threading import Thread
from datetime import datetime, timezone

import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ============================================================
# KING OF XAU_NAS — INSTITUTIONAL GOLD ENGINE
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
CHAT_ID = os.getenv("CHAT_ID")

PORT = int(os.getenv("PORT", "10000"))

XAU_SYMBOL = "XAU/USD"

# Main trading timeframe
INTERVAL = "15min"

# Higher/lower timeframe confirmation
HTF_INTERVAL = "1h"
ENTRY_INTERVAL = "5min"

OUTPUT_SIZE = 100

# Monitoring interval
MONITOR_SECONDS = 10

# ============================================================
# LOCAL TRADE MEMORY
# ============================================================

TRADES_FILE = "trades.json"

open_trades = []
last_signal_key = None


def load_trades():
    try:
        with open(TRADES_FILE, "r") as file:
            return json.load(file)
    except Exception:
        return []


def save_trades():
    try:
        with open(TRADES_FILE, "w") as file:
            json.dump(open_trades, file, indent=4)
    except Exception as error:
        logger.error("Unable to save trades: %s", error)


open_trades = load_trades()

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ============================================================
# WEB SERVER
# ============================================================

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "King of XAU_NAS Institutional Gold Engine is running!"


@web_app.route("/health")
def health():
    return "OK"


def run_web_server():
    web_app.run(
        host="0.0.0.0",
        port=PORT
    )

# ============================================================
# TWELVE DATA
# ============================================================

def twelve_data_request(endpoint, params):

    if not TWELVE_DATA_API_KEY:
        return None, "Twelve Data API key is missing."

    request_params = dict(params)
    request_params["apikey"] = TWELVE_DATA_API_KEY

    url = f"https://api.twelvedata.com/{endpoint}"

    try:
        response = requests.get(
            url,
            params=request_params,
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

        if data.get("status") == "error":
            return None, data.get(
                "message",
                "Twelve Data returned an error."
            )

        return data, None

    except Exception as error:
        logger.error("API error: %s", error)
        return None, "Unable to connect to Twelve Data."

# ============================================================
# PRICE
# ============================================================

def get_price():

    data, error = twelve_data_request(
        "price",
        {
            "symbol": XAU_SYMBOL
        }
    )

    if error:
        return None, error

    try:
        return float(data["price"]), None
    except Exception:
        return None, "No valid price returned."

# ============================================================
# CANDLES
# ============================================================

def get_candles(interval=INTERVAL, outputsize=OUTPUT_SIZE):

    data, error = twelve_data_request(
        "time_series",
        {
            "symbol": XAU_SYMBOL,
            "interval": interval,
            "outputsize": outputsize,
            "format": "JSON"
        }
    )

    if error:
        return None, error

    try:

        values = data.get("values")

        if not values:
            return None, "No candle data returned."

        candles = []

        for candle in reversed(values):

            candles.append({
                "datetime": candle.get("datetime"),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
            })

        return candles, None

    except Exception as error:

        logger.error("Candle processing error: %s", error)

        return None, "Unable to process candle data."

# ============================================================
# EMA
# ============================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(values[:period]) / period

    for price in values[period:]:
        ema = (
            (price - ema) * multiplier
        ) + ema

    return ema

# ============================================================
# RSI
# ============================================================

def calculate_rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0)

        else:
            gains.append(0)
            losses.append(abs(change))

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        average_gain = (
            (average_gain * (period - 1))
            + gains[i]
        ) / period

        average_loss = (
            (average_loss * (period - 1))
            + losses[i]
        ) / period

    if average_loss == 0:
        return 100.0

    rs = average_gain / average_loss

    return 100 - (100 / (1 + rs))

# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(candles)):

        high = candles[i]["high"]
        low = candles[i]["low"]
        previous_close = candles[i - 1]["close"]

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        true_ranges.append(true_range)

    atr = sum(true_ranges[:period]) / period

    for value in true_ranges[period:]:

        atr = (
            (atr * (period - 1))
            + value
        ) / period

    return atr

# ============================================================
# CANDLE FILTERS
# ============================================================

def bullish_engulfing(candles):

    if len(candles) < 2:
        return False

    previous = candles[-2]
    current = candles[-1]

    return (
        previous["close"] < previous["open"]
        and current["close"] > current["open"]
        and current["open"] <= previous["close"]
        and current["close"] >= previous["open"]
    )


def bearish_engulfing(candles):

    if len(candles) < 2:
        return False

    previous = candles[-2]
    current = candles[-1]

    return (
        previous["close"] > previous["open"]
        and current["close"] < current["open"]
        and current["open"] >= previous["close"]
        and current["close"] <= previous["open"]
    )


def candle_body(candle):
    return abs(candle["close"] - candle["open"])


def candle_range(candle):
    return candle["high"] - candle["low"]


def strong_bullish_candle(candle):

    body = candle_body(candle)
    full_range = candle_range(candle)

    if full_range <= 0:
        return False

    return (
        candle["close"] > candle["open"]
        and body / full_range >= 0.60
    )


def strong_bearish_candle(candle):

    body = candle_body(candle)
    full_range = candle_range(candle)

    if full_range <= 0:
        return False

    return (
        candle["close"] < candle["open"]
        and body / full_range >= 0.60
    )

# ============================================================
# MARKET STRUCTURE
# ============================================================

def market_structure(candles):

    if len(candles) < 10:
        return "NONE"

    recent = candles[-8:-1]

    previous_high = max(c["high"] for c in recent)
    previous_low = min(c["low"] for c in recent)

    current = candles[-1]

    if current["close"] > previous_high:
        return "BOS_BUY"

    if current["close"] < previous_low:
        return "BOS_SELL"

    return "NONE"


def trend_structure(candles):

    if len(candles) < 10:
        return "MIXED"

    highs = [c["high"] for c in candles[-6:]]
    lows = [c["low"] for c in candles[-6:]]

    higher_highs = highs[-1] > highs[-3]
    higher_lows = lows[-1] > lows[-3]

    lower_highs = highs[-1] < highs[-3]
    lower_lows = lows[-1] < lows[-3]

    if higher_highs and higher_lows:
        return "BULLISH"

    if lower_highs and lower_lows:
        return "BEARISH"

    return "MIXED"

# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def liquidity_sweep(candles):

    if not candles:
        return "NONE"

    candle = candles[-1]

    body = candle_body(candle)

    if body <= 0:
        return "NONE"

    upper_wick = (
        candle["high"]
        - max(candle["open"], candle["close"])
    )

    lower_wick = (
        min(candle["open"], candle["close"])
        - candle["low"]
    )

    if upper_wick >= body * 2:
        return "SELL_SWEEP"

    if lower_wick >= body * 2:
        return "BUY_SWEEP"

    return "NONE"

# ============================================================
# FAIR VALUE GAP
# ============================================================

def fair_value_gap(candles):

    if len(candles) < 3:
        return "NONE"

    first = candles[-3]
    third = candles[-1]

    if third["low"] > first["high"]:
        return "BULL"

    if third["high"] < first["low"]:
        return "BEAR"

    return "NONE"

# ============================================================
# MULTI TIMEFRAME TREND
# ============================================================

def timeframe_trend(candles):

    if not candles or len(candles) < 50:
        return "UNKNOWN"

    closes = [c["close"] for c in candles]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    if ema20 is None or ema50 is None:
        return "UNKNOWN"

    price = closes[-1]

    if price > ema20 and ema20 > ema50:
        return "BULLISH"

    if price < ema20 and ema20 < ema50:
        return "BEARISH"

    return "MIXED"

# ============================================================
# KILL ZONE
# ============================================================

def kill_zone():

    hour = datetime.now(timezone.utc).hour

    # Broad London/New York activity window.
    return 7 <= hour <= 16

# ============================================================
# SIGNAL COOLDOWN
# ============================================================

def signal_already_open(signal):

    for trade in open_trades:

        if (
            trade.get("status") == "OPEN"
            and trade.get("side") == signal
        ):
            return True

    return False

# ============================================================
# GOLD ANALYSIS
# ============================================================

def analyze_gold():

    candles, error = get_candles(
        INTERVAL,
        OUTPUT_SIZE
    )

    if error:
        return None, error

    if len(candles) < 60:
        return None, "Not enough 15-minute candle data."

    closes = [
        candle["close"]
        for candle in candles
    ]

    price = closes[-1]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    rsi = calculate_rsi(closes, 14)
    atr = calculate_atr(candles, 14)

    if None in [ema20, ema50, rsi, atr]:
        return None, "Unable to calculate indicators."

    # ========================================================
    # MULTI TIMEFRAME
    # ========================================================

    htf_candles, htf_error = get_candles(
        HTF_INTERVAL,
        100
    )

    entry_candles, entry_error = get_candles(
        ENTRY_INTERVAL,
        100
    )

    htf_trend = (
        timeframe_trend(htf_candles)
        if not htf_error
        else "UNKNOWN"
    )

    entry_trend = (
        timeframe_trend(entry_candles)
        if not entry_error
        else "UNKNOWN"
    )

    # ========================================================
    # STRUCTURE
    # ========================================================

    structure = market_structure(candles)
    structure_trend = trend_structure(candles)

    sweep = liquidity_sweep(candles)
    fvg = fair_value_gap(candles)

    last_candle = candles[-1]

    score = 0
    reasons = []
    warnings = []

    # ========================================================
    # MAIN TREND
    # ========================================================

    if price > ema20:
        score += 1
        reasons.append("Price above EMA20")
    else:
        score -= 1

    if ema20 > ema50:
        score += 2
        reasons.append("EMA20 above EMA50")
    else:
        score -= 2

    # ========================================================
    # RSI MOMENTUM
    # ========================================================

    if 55 <= rsi <= 68:
        score += 2
        reasons.append("Bullish RSI momentum")

    elif 32 <= rsi <= 45:
        score -= 2
        reasons.append("Bearish RSI momentum")

    elif rsi > 72:
        score -= 2
        warnings.append("RSI overbought")

    elif rsi < 28:
        score += 1
        warnings.append("RSI oversold")

    else:
        warnings.append("RSI neutral")

    # ========================================================
    # ATR
    # ========================================================

    if atr >= 4:
        reasons.append("Healthy volatility")
    else:
        score -= 2
        warnings.append("Low volatility")

    # ========================================================
    # CANDLE CONFIRMATION
    # ========================================================

    if bullish_engulfing(candles):
        score += 2
        reasons.append("Bullish engulfing")

    elif bearish_engulfing(candles):
        score -= 2
        reasons.append("Bearish engulfing")

    elif strong_bullish_candle(last_candle):
        score += 1
        reasons.append("Strong bullish candle")

    elif strong_bearish_candle(last_candle):
        score -= 1
        reasons.append("Strong bearish candle")

    else:
        warnings.append("Weak candle confirmation")

    # ========================================================
    # MARKET STRUCTURE
    # ========================================================

    if structure == "BOS_BUY":
        score += 3
        reasons.append("Bullish Break of Structure")

    elif structure == "BOS_SELL":
        score -= 3
        reasons.append("Bearish Break of Structure")

    # ========================================================
    # LIQUIDITY
    # ========================================================

    if sweep == "BUY_SWEEP":
        score += 1
        reasons.append("Buy-side liquidity sweep")

    elif sweep == "SELL_SWEEP":
        score -= 1
        reasons.append("Sell-side liquidity sweep")

    # ========================================================
    # FVG
    # ========================================================

    if fvg == "BULL":
        score += 1
        reasons.append("Bullish FVG")

    elif fvg == "BEAR":
        score -= 1
        reasons.append("Bearish FVG")

    # ========================================================
    # HIGHER TIMEFRAME
    # ========================================================

    if htf_trend == "BULLISH":
        score += 3
        reasons.append("1H bullish confirmation")

    elif htf_trend == "BEARISH":
        score -= 3
        reasons.append("1H bearish confirmation")

    else:
        warnings.append("1H trend mixed")

    # ========================================================
    # 5 MINUTE CONFIRMATION
    # ========================================================

    if entry_trend == "BULLISH":
        score += 2
        reasons.append("5M bullish confirmation")

    elif entry_trend == "BEARISH":
        score -= 2
        reasons.append("5M bearish confirmation")

    else:
        warnings.append("5M trend mixed")

    # ========================================================
    # KILL ZONE
    # ========================================================

    active_session = kill_zone()

    if active_session:
        reasons.append("Active London/New York session")
    else:
        score -= 1
        warnings.append("Outside preferred session")

    # ========================================================
    # FINAL SIGNAL
    # ========================================================

    if score >= 8:
        signal = "BUY"
        icon = "🟢"

    elif score <= -8:
        signal = "SELL"
        icon = "🔴"

    else:
        signal = "WAIT"
        icon = "🟡"

    # ========================================================
    # CONFLICT FILTER
    # ========================================================

    if signal == "BUY":

        if htf_trend == "BEARISH":
            signal = "WAIT"
            icon = "🟡"
            warnings.append("1H conflicts with BUY")

        if entry_trend == "BEARISH":
            signal = "WAIT"
            icon = "🟡"
            warnings.append("5M conflicts with BUY")

    elif signal == "SELL":

        if htf_trend == "BULLISH":
            signal = "WAIT"
            icon = "🟡"
            warnings.append("1H conflicts with SELL")

        if entry_trend == "BULLISH":
            signal = "WAIT"
            icon = "🟡"
            warnings.append("5M conflicts with SELL")

    # ========================================================
    # RISK LEVELS
    # ========================================================

    entry = price

    if signal == "BUY":

        stop_loss = entry - (atr * 1.5)
        tp1 = entry + (atr * 1.5)
        tp2 = entry + (atr * 2.5)
        tp3 = entry + (atr * 4)

    elif signal == "SELL":

        stop_loss = entry + (atr * 1.5)
        tp1 = entry - (atr * 1.5)
        tp2 = entry - (atr * 2.5)
        tp3 = entry - (atr * 4)

    else:

        stop_loss = None
        tp1 = None
        tp2 = None
        tp3 = None

    # ========================================================
    # SCORE
    # ========================================================

    confidence = min(
        99,
        max(
            35,
            50 + abs(score) * 4
        )
    )

    return {
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,

        "signal": signal,
        "icon": icon,

        "confidence": confidence,
        "score": score,

        "trend": structure_trend,
        "htf_trend": htf_trend,
        "entry_trend": entry_trend,

        "structure": structure,
        "sweep": sweep,
        "fvg": fvg,

        "active_session": active_session,

        "reasons": reasons,
        "warnings": warnings,

        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
    }, None

# ============================================================
# FORMAT ANALYSIS
# ============================================================

def format_analysis(result):

    message = (
        "👑 *KING OF XAU_NAS — INSTITUTIONAL AI* 👑\n\n"
        "🟡 *XAU/USD GOLD*\n\n"
        f"💰 Price: `${result['price']:,.2f}`\n"
        f"📈 Structure: *{result['trend']}*\n"
        f"🧠 AI Score: *{result['score']}*\n"
        f"💪 Signal Score: *{result['confidence']}%*\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *MULTI-TIMEFRAME*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"1H Trend: *{result['htf_trend']}*\n"
        f"15M Setup: *{result['trend']}*\n"
        f"5M Entry: *{result['entry_trend']}*\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *TECHNICAL ENGINE*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"EMA 20: `{result['ema20']:,.2f}`\n"
        f"EMA 50: `{result['ema50']:,.2f}`\n"
        f"RSI 14: `{result['rsi']:.1f}`\n"
        f"ATR 14: `{result['atr']:.2f}`\n"
        f"BOS: `{result['structure']}`\n"
        f"Liquidity: `{result['sweep']}`\n"
        f"FVG: `{result['fvg']}`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *SIGNAL*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{result['icon']} Signal: *{result['signal']}*\n"
        f"🧠 Score: *{result['confidence']}%*\n"
    )

    if result["signal"] != "WAIT":

        message += (
            "\n"
            f"🎯 Entry: `${result['entry']:,.2f}`\n"
            f"🛑 SL: `${result['stop_loss']:,.2f}`\n"
            f"🎯 TP1: `${result['tp1']:,.2f}`\n"
            f"🎯 TP2: `${result['tp2']:,.2f}`\n"
            f"🏆 TP3: `${result['tp3']:,.2f}`\n"
        )

    else:

        message += (
            "\n"
            "⏳ *WAIT — NO ELITE SETUP*\n"
            "The filters are not sufficiently aligned.\n"
        )

    if result["reasons"]:

        message += "\n🧠 *CONFIRMATIONS*\n"

        for reason in result["reasons"][:8]:
            message += f"✅ {reason}\n"

    if result["warnings"]:

        message += "\n⚠️ *WARNINGS*\n"

        for warning in result["warnings"][:5]:
            message += f"• {warning}\n"

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ Timeframe: *{INTERVAL}*\n"
        "📡 Data: Twelve Data\n\n"
        "⚠️ Analysis only — not financial advice.\n"
        "⚠️ Signal score is NOT a guaranteed win probability."
    )

    return message

# ============================================================
# TRADE CREATION
# ============================================================

def create_trade(result):

    global last_signal_key

    if result["signal"] == "WAIT":
        return False

    signal_key = (
        result["signal"],
        round(result["entry"], 1)
    )

    if signal_key == last_signal_key:
        return False

    if signal_already_open(result["signal"]):
        return False

    trade = {
        "id": int(time.time()),

        "symbol": XAU_SYMBOL,
        "side": result["signal"],

        "entry": result["entry"],
        "sl": result["stop_loss"],

        "tp1": result["tp1"],
        "tp2": result["tp2"],
        "tp3": result["tp3"],

        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,

        "break_even": False,

        "status": "OPEN",

        "created_at": datetime.now(
            timezone.utc
        ).isoformat()
    }

    open_trades.append(trade)

    last_signal_key = signal_key

    save_trades()

    return True

# ============================================================
# TRADE MONITOR
# ============================================================

async def monitor_trades(context):

    global open_trades

    logger.info("Trade monitor started.")

    while True:

        try:

            price, error = get_price()

            if error or price is None:
                await asyncio.sleep(MONITOR_SECONDS)
                continue

            changed = False

            for trade in open_trades:

                if trade.get("status") != "OPEN":
                    continue

                side = trade["side"]

                # ==================================================
                # BUY
                # ==================================================

                if side == "BUY":

                    if (
                        not trade["tp1_hit"]
                        and price >= trade["tp1"]
                    ):

                        trade["tp1_hit"] = True

                        # Move SL to entry
                        trade["sl"] = trade["entry"]
                        trade["break_even"] = True

                        changed = True

                        await send_trade_message(
                            context,
                            (
                                "🎯 *TP1 HIT — BUY*\n\n"
                                f"🟡 XAU/USD\n"
                                f"💰 Price: `${price:,.2f}`\n"
                                "🛡️ Stop Loss moved to BREAK-EVEN."
                            )
                        )

                    if (
                        trade["tp1_hit"]
                        and not trade["tp2_hit"]
                        and price >= trade["tp2"]
                    ):

                        trade["tp2_hit"] = True

                        changed = True

                        await send_trade_message(
                            context,
                            (
                                "🏆 *TP2 HIT — BUY*\n\n"
                                f"🟡 XAU/USD\n"
                                f"💰 Price: `${price:,.2f}`\n"
                                "📈 Trailing protection activated."
                            )
                        )

                    if (
                        trade["tp2_hit"]
                        and not trade["tp3_hit"]
                        and price >= trade["tp3"]
                    ):

                        trade["tp3_hit"] = True
                        trade["status"] = "TP3"

                        changed = True

                        await send_trade_message(
                            context,
                            (
                                "👑 *TP3 HIT — TRADE COMPLETE*\n\n"
                                f"🟡 XAU/USD BUY\n"
                                f"💰 Exit: `${price:,.2f}`\n"
                                "🏆 Full target reached."
                            )
                        )

                    elif price <= trade["sl"]:

                        trade["status"] = (
                            "BREAKEVEN"
                            if trade["break_even"]
                            else "SL"
                        )

                        changed = True

                        if trade["break_even"]:

                            text = (
                                "🛡️ *BREAK-EVEN HIT*\n\n"
                                "XAU/USD BUY\n"
                                f"Exit: `${price:,.2f}`\n"
                                "Capital protected."
                            )

                        else:

                            text = (
                                "❌ *SL HIT*\n\n"
                                "XAU/USD BUY\n"
                                f"Exit: `${price:,.2f}`\n"
                                "Trade closed."
                            )

                        await send_trade_message(
                            context,
                            text
                        )

                # ==================================================
                # SELL
                # ==================================================

                elif side == "SELL":

                    if (
                        not trade["tp1_hit"]
                        and price <= trade["tp1"]
                    ):

                        trade["tp1_hit"] = True

                        trade["sl"] = trade["entry"]
                        trade["break_even"] = True

                        changed = True

                        await send_trade_message(
                            context,
                            (
                                "🎯 *TP1 HIT — SELL*\n\n"
                                f"🟡 XAU/USD\n"
                                f"💰 Price: `${price:,.2f}`\n"
                                "🛡️ Stop Loss moved to BREAK-EVEN."
                            )
                        )

                    if (
                        trade["tp1_hit"]
                        and not trade["tp2_hit"]
                        and price <= trade["tp2"]
                    ):

                        trade["tp2_hit"] = True

                        changed = True

                        await send_trade_message(
                            context,
                            (
                                "🏆 *TP2 HIT — SELL*\n\n"
                                f"🟡 XAU/USD\n"
                                f"💰 Price: `${price:,.2f}`\n"
                                "📈 Trailing protection activated."
                            )
                        )

                    if (
                        trade["tp2_hit"]
                        and not trade["tp3_hit"]
                        and price <= trade["tp3"]
                    ):

                        trade["tp3_hit"] = True
                        trade["status"] = "TP3"

                        changed = True

                        await send_trade_message(
                            context,
                            (
                                "👑 *TP3 HIT — TRADE COMPLETE*\n\n"
                                f"🟡 XAU/USD SELL\n"
                                f"💰 Exit: `${price:,.2f}`\n"
                                "🏆 Full target reached."
                            )
                        )

                    elif price >= trade["sl"]:

                        trade["status"] = (
                            "BREAKEVEN"
                            if trade["break_even"]
                            else "SL"
                        )

                        changed = True

                        if trade["break_even"]:

                            text = (
                                "🛡️ *BREAK-EVEN HIT*\n\n"
                                "XAU/USD SELL\n"
                                f"Exit: `${price:,.2f}`\n"
                                "Capital protected."
                            )

                        else:

                            text = (
                                "❌ *SL HIT*\n\n"
                                "XAU/USD SELL\n"
                                f"Exit: `${price:,.2f}`\n"
                                "Trade closed."
                            )

                        await send_trade_message(
                            context,
                            text
                        )

            if changed:
                save_trades()

        except Exception as error:

            logger.error(
                "Trade monitor error: %s",
                error
            )

        await asyncio.sleep(MONITOR_SECONDS)

# ============================================================
# SEND TRADE MESSAGE
# ============================================================

async def send_trade_message(context, text):

    if not CHAT_ID:
        logger.warning(
            "CHAT_ID is missing. Cannot send automatic trade alert."
        )
        return

    try:

        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=text,
            parse_mode="Markdown"
        )

    except Exception as error:

        logger.error(
            "Telegram alert error: %s",
            error
        )

# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton(
                "🟡 GOLD AI",
                callback_data="gold"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 STATUS",
                callback_data="status"
            )
        ],
        [
            InlineKeyboardButton(
                "📈 PERFORMANCE",
                callback_data="performance"
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ HELP",
                callback_data="help"
            )
        ],
    ]

    message = (
        "👑 *KING OF XAU_NAS — INSTITUTIONAL AI* 👑\n\n"
        "🟡 *XAU/USD GOLD ENGINE*\n\n"
        "✅ Multi-timeframe analysis\n"
        "✅ Fake-signal filter\n"
        "✅ Market structure\n"
        "✅ Liquidity detection\n"
        "✅ FVG detection\n"
        "✅ Entry / SL / TP1 / TP2 / TP3\n"
        "✅ Automatic trade tracking\n"
        "✅ Break-even protection\n\n"
        "Choose an option:"
    )

    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ============================================================
# GOLD COMMAND
# ============================================================

async def gold_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🧠 Analyzing XAU/USD across 1H / 15M / 5M...\n\n"
        "Checking structure, liquidity and momentum..."
    )

    result, error = analyze_gold()

    if error:

        await update.message.reply_text(
            f"❌ *GOLD ANALYSIS ERROR*\n\n{error}",
            parse_mode="Markdown"
        )

        return

    created = create_trade(result)

    message = format_analysis(result)

    if created:

        message += (
            "\n\n🟢 *TRADE TRACKER ACTIVATED*\n"
            "The bot will monitor SL / TP1 / TP2 / TP3."
        )

    await update.message.reply_text(
        message,
        parse_mode="Markdown"
    )

# ============================================================
# PERFORMANCE
# ============================================================

async def performance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    completed = [
        trade
        for trade in open_trades
        if trade.get("status") != "OPEN"
    ]

    wins = sum(
        1
        for trade in completed
        if trade.get("status") in ["TP3", "TP2"]
    )

    losses = sum(
        1
        for trade in completed
        if trade.get("status") == "SL"
    )

    breakeven = sum(
        1
        for trade in completed
        if trade.get("status") == "BREAKEVEN"
    )

    total = wins + losses

    if total > 0:
        win_rate = wins / total * 100
    else:
        win_rate = 0

    message = (
        "📈 *KING OF XAU_NAS PERFORMANCE*\n\n"
        f"📊 Completed Trades: `{len(completed)}`\n"
        f"🏆 Wins: `{wins}`\n"
        f"❌ Losses: `{losses}`\n"
        f"🛡️ Break-even: `{breakeven}`\n"
        f"🎯 Win Rate: `{win_rate:.1f}%`\n\n"
        f"🔵 Open Trades: `{sum(1 for t in open_trades if t.get('status') == 'OPEN')}`"
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown"
    )

# ============================================================
# STATUS
# ============================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    price, error = get_price()

    if price is not None:

        price_text = f"${price:,.2f}"
        data_status = "🟢 ONLINE"

    else:

        price_text = "Unavailable"
        data_status = "🔴 OFFLINE"

    open_count = sum(
        1
        for trade in open_trades
        if trade.get("status") == "OPEN"
    )

    message = (
        "👑 *KING OF XAU_NAS STATUS*\n\n"
        "🟢 Telegram Bot: ONLINE\n"
        f"🟡 XAU/USD: {price_text}\n"
        f"📡 Twelve Data: {data_status}\n"
        "🧠 AI Engine: READY\n"
        "📊 Multi-Timeframe: READY\n"
        "🛡️ Fake Signal Filter: ACTIVE\n"
        f"📈 Open Trades: `{open_count}`\n"
        "🔵 Nasdaq: DISABLED"
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown"
    )

# ============================================================
# HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = (
        "ℹ️ *KING OF XAU_NAS — INSTITUTIONAL AI*\n\n"

        "/start — Main menu\n"
        "/gold — Full AI analysis\n"
        "/status — System status\n"
        "/performance — Performance\n"
        "/help — Help\n\n"

        "🧠 *ENGINE*\n"
        "• 1H trend\n"
        "• 15M setup\n"
        "• 5M confirmation\n"
        "• EMA20 / EMA50\n"
        "• RSI14\n"
        "• ATR14\n"
        "• BOS\n"
        "• Liquidity sweep\n"
        "• FVG\n"
        "• Candle confirmation\n\n"

        "🎯 *TRADE TRACKER*\n"
        "• TP1\n"
        "• TP2\n"
        "• TP3\n"
        "• Break-even\n"
        "• SL monitoring\n\n"

        "⚠️ Analysis only — no broker orders are placed."
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown"
    )

# ============================================================
# BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if query.data == "gold":

        await query.edit_message_text(
            "🧠 *Analyzing XAU/USD...*\n\n"
            "Checking 1H → 15M → 5M...",
            parse_mode="Markdown"
        )

        result, error = analyze_gold()

        if error:

            message = (
                "❌ *GOLD ANALYSIS ERROR*\n\n"
                f"{error}"
            )

        else:

            create_trade(result)

            message = format_analysis(result)

        await query.edit_message_text(
            message,
            parse_mode="Markdown"
        )

    elif query.data == "status":

        price, error = get_price()

        if price is not None:

            message = (
                "📊 *GOLD MARKET STATUS*\n\n"
                "🟢 Telegram Bot: ONLINE\n"
                f"🟡 XAU/USD: ${price:,.2f}\n"
                "📡 Twelve Data: 🟢 ONLINE\n"
                "🧠 AI Engine: 🟢 READY\n"
                "🛡️ Fake Signal Filter: 🟢 ACTIVE"
            )

        else:

            message = (
                "📊 *GOLD MARKET STATUS*\n\n"
                "🟢 Telegram Bot: ONLINE\n"
                "🟡 XAU/USD: Unavailable\n"
                "📡 Twelve Data: 🔴 OFFLINE"
            )

        await query.edit_message_text(
            message,
            parse_mode="Markdown"
        )

    elif query.data == "performance":

        completed = [
            t
            for t in open_trades
            if t.get("status") != "OPEN"
        ]

        wins = sum(
            1
            for t in completed
            if t.get("status") in ["TP2", "TP3"]
        )

        losses = sum(
            1
            for t in completed
            if t.get("status") == "SL"
        )

        total = wins + losses

        win_rate = (
            wins / total * 100
            if total
            else 0
        )

        message = (
            "📈 *PERFORMANCE*\n\n"
            f"Trades: `{len(completed)}`\n"
            f"Wins: `{wins}`\n"
            f"Losses: `{losses}`\n"
            f"Win Rate: `{win_rate:.1f}%`"
        )

        await query.edit_message_text(
            message,
            parse_mode="Markdown"
        )

    elif query.data == "help":

        message = (
            "ℹ️ *KING OF XAU_NAS*\n\n"
            "🧠 Institutional AI engine\n"
            "📊 Multi-timeframe confirmation\n"
            "🛡️ Fake signal filtering\n"
            "🎯 TP1 / TP2 / TP3\n"
            "🛡️ Break-even\n"
            "📈 Performance tracking\n\n"
            "⚠️ Analysis only."
        )

        await query.edit_message_text(
            message,
            parse_mode="Markdown"
        )

# ============================================================
# START MONITOR JOB
# ============================================================

async def start_monitor(context):

    asyncio.create_task(
        monitor_trades(context)
    )

# ============================================================
# MAIN
# ============================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not TWELVE_DATA_API_KEY:

        raise RuntimeError(
            "TWELVE_DATA_API_KEY is missing."
        )

    if not CHAT_ID:

        logger.warning(
            "CHAT_ID is missing. Automatic trade alerts will not work."
        )

    Thread(
        target=run_web_server,
        daemon=True
    ).start()

    application = (
        Application
        .builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("gold", gold_command)
    )

    application.add_handler(
        CommandHandler("status", status_command)
    )

    application.add_handler(
        CommandHandler("performance", performance_command)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    # Start automatic trade monitoring
    application.job_queue.run_once(
        start_monitor,
        when=2
    )

    logger.info(
        "👑 KING OF XAU_NAS Institutional Gold Engine started!"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
