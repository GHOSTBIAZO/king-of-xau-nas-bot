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
# 👑 KING OF XAU_NAS — INSTITUTIONAL GOLD TELEGRAM ENGINE
# ============================================================
#
# TELEGRAM SIGNAL ENGINE
# XAU/USD ONLY
#
# Includes:
# 1H + 15M + 5M confirmation
# EMA20 / EMA50
# RSI14
# ATR14
# Break of Structure
# Liquidity sweep
# Fair Value Gap
# Candle confirmation
# Automatic scanner
# BUY / SELL signals
# BUY STOP / SELL STOP alerts
# BUY LIMIT / SELL LIMIT alerts
# TP1 / TP2 / TP3
# Break-even
# Dynamic trailing protection
# Trade tracking
# Performance
#
# IMPORTANT:
# This bot DOES NOT place broker orders.
# It only sends signals/alerts through Telegram.
# ============================================================


# ============================================================
# SETTINGS
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
CHAT_ID = os.getenv("CHAT_ID")

PORT = int(os.getenv("PORT", "10000"))

XAU_SYMBOL = "XAU/USD"

MAIN_INTERVAL = "15min"
HTF_INTERVAL = "1h"
ENTRY_INTERVAL = "5min"

OUTPUT_SIZE = 100

# Automatic scanner
SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "300"))

# Trade monitoring
MONITOR_SECONDS = int(os.getenv("MONITOR_SECONDS", "15"))

# Minimum score for signal
SIGNAL_SCORE = 8

# Minimum signal strength
MIN_CONFIDENCE = 82

# Local trade database
TRADES_FILE = "trades.json"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("KING_OF_XAU_NAS")


# ============================================================
# WEB SERVER FOR RENDER
# ============================================================

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "KING OF XAU_NAS Institutional Gold Engine is running!"


@web_app.route("/health")
def health():
    return "OK"


def run_web_server():

    web_app.run(
        host="0.0.0.0",
        port=PORT
    )


# ============================================================
# TRADE MEMORY
# ============================================================

def load_trades():

    try:

        with open(
            TRADES_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

            if isinstance(data, list):
                return data

    except Exception:
        pass

    return []


open_trades = load_trades()

last_signal_key = None
last_scanned_candle = None

scanner_enabled = True


def save_trades():

    try:

        temporary_file = TRADES_FILE + ".tmp"

        with open(
            temporary_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                open_trades,
                file,
                indent=4
            )

        os.replace(
            temporary_file,
            TRADES_FILE
        )

    except Exception as error:

        logger.error(
            "Trade database error: %s",
            error
        )


# ============================================================
# TWELVE DATA REQUEST
# ============================================================

def twelve_data_request(
    endpoint,
    params
):

    if not TWELVE_DATA_API_KEY:

        return None, "Twelve Data API key is missing."

    request_params = dict(params)

    request_params["apikey"] = TWELVE_DATA_API_KEY

    url = (
        "https://api.twelvedata.com/"
        + endpoint
    )

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

        logger.error(
            "Twelve Data error: %s",
            error
        )

        return None, (
            "Unable to connect to Twelve Data."
        )


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

        return float(
            data["price"]
        ), None

    except Exception:

        return None, (
            "No valid GOLD price returned."
        )


# ============================================================
# CANDLES
# ============================================================

def get_candles(
    interval=MAIN_INTERVAL,
    outputsize=OUTPUT_SIZE
):

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

            return None, (
                "No candle data returned."
            )

        candles = []

        for candle in reversed(values):

            candles.append(
                {
                    "datetime": candle.get(
                        "datetime"
                    ),
                    "open": float(
                        candle["open"]
                    ),
                    "high": float(
                        candle["high"]
                    ),
                    "low": float(
                        candle["low"]
                    ),
                    "close": float(
                        candle["close"]
                    )
                }
            )

        return candles, None

    except Exception as error:

        logger.error(
            "Candle processing error: %s",
            error
        )

        return None, (
            "Unable to process candle data."
        )


# ============================================================
# EMA
# ============================================================

def calculate_ema(
    values,
    period
):

    if len(values) < period:
        return None

    multiplier = (
        2 / (period + 1)
    )

    ema = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    values,
    period=14
):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        change = (
            values[i]
            - values[i - 1]
        )

        if change > 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

    average_gain = (
        sum(gains[:period])
        / period
    )

    average_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        average_gain = (
            (
                average_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        average_loss = (
            (
                average_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if average_loss == 0:
        return 100.0

    rs = (
        average_gain
        / average_loss
    )

    return (
        100
        - (
            100
            / (1 + rs)
        )
    )


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    candles,
    period=14
):

    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(
        1,
        len(candles)
    ):

        high = candles[i]["high"]
        low = candles[i]["low"]

        previous_close = (
            candles[i - 1]["close"]
        )

        true_range = max(
            high - low,
            abs(
                high
                - previous_close
            ),
            abs(
                low
                - previous_close
            )
        )

        true_ranges.append(
            true_range
        )

    atr = (
        sum(
            true_ranges[:period]
        )
        / period
    )

    for value in true_ranges[period:]:

        atr = (
            (
                atr
                * (period - 1)
            )
            + value
        ) / period

    return atr


# ============================================================
# CANDLE ANALYSIS
# ============================================================

def candle_body(candle):

    return abs(
        candle["close"]
        - candle["open"]
    )


def candle_range(candle):

    return (
        candle["high"]
        - candle["low"]
    )


def bullish_engulfing(candles):

    if len(candles) < 2:
        return False

    previous = candles[-2]
    current = candles[-1]

    return (
        previous["close"]
        < previous["open"]
        and current["close"]
        > current["open"]
        and current["open"]
        <= previous["close"]
        and current["close"]
        >= previous["open"]
    )


def bearish_engulfing(candles):

    if len(candles) < 2:
        return False

    previous = candles[-2]
    current = candles[-1]

    return (
        previous["close"]
        > previous["open"]
        and current["close"]
        < current["open"]
        and current["open"]
        >= previous["close"]
        and current["close"]
        <= previous["open"]
    )


def strong_bullish_candle(candle):

    body = candle_body(candle)
    full_range = candle_range(candle)

    if full_range <= 0:
        return False

    return (
        candle["close"]
        > candle["open"]
        and body / full_range
        >= 0.60
    )


def strong_bearish_candle(candle):

    body = candle_body(candle)
    full_range = candle_range(candle)

    if full_range <= 0:
        return False

    return (
        candle["close"]
        < candle["open"]
        and body / full_range
        >= 0.60
    )


# ============================================================
# MARKET STRUCTURE
# ============================================================

def market_structure(candles):

    if len(candles) < 10:
        return "NONE"

    recent = candles[-8:-1]

    previous_high = max(
        c["high"]
        for c in recent
    )

    previous_low = min(
        c["low"]
        for c in recent
    )

    current = candles[-1]

    if current["close"] > previous_high:
        return "BOS_BUY"

    if current["close"] < previous_low:
        return "BOS_SELL"

    return "NONE"


def trend_structure(candles):

    if len(candles) < 10:
        return "MIXED"

    highs = [
        c["high"]
        for c in candles[-6:]
    ]

    lows = [
        c["low"]
        for c in candles[-6:]
    ]

    higher_highs = (
        highs[-1]
        > highs[-3]
    )

    higher_lows = (
        lows[-1]
        > lows[-3]
    )

    lower_highs = (
        highs[-1]
        < highs[-3]
    )

    lower_lows = (
        lows[-1]
        < lows[-3]
    )

    if (
        higher_highs
        and higher_lows
    ):

        return "BULLISH"

    if (
        lower_highs
        and lower_lows
    ):

        return "BEARISH"

    return "MIXED"


# ============================================================
# LIQUIDITY
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
        - max(
            candle["open"],
            candle["close"]
        )
    )

    lower_wick = (
        min(
            candle["open"],
            candle["close"]
        )
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

    if (
        third["low"]
        > first["high"]
    ):

        return "BULL"

    if (
        third["high"]
        < first["low"]
    ):

        return "BEAR"

    return "NONE"


# ============================================================
# TIMEFRAME TREND
# ============================================================

def timeframe_trend(candles):

    if (
        not candles
        or len(candles) < 50
    ):

        return "UNKNOWN"

    closes = [
        c["close"]
        for c in candles
    ]

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    if (
        ema20 is None
        or ema50 is None
    ):

        return "UNKNOWN"

    price = closes[-1]

    if (
        price > ema20
        and ema20 > ema50
    ):

        return "BULLISH"

    if (
        price < ema20
        and ema20 < ema50
    ):

        return "BEARISH"

    return "MIXED"


# ============================================================
# TRADING SESSION
# ============================================================

def kill_zone():

    hour = datetime.now(
        timezone.utc
    ).hour

    return (
        7 <= hour <= 16
    )


# ============================================================
# PENDING ORDER CALCULATOR
# ============================================================

def build_pending_orders(
    candles,
    atr,
    signal
):

    if (
        len(candles) < 3
        or not atr
    ):

        return []

    last = candles[-1]
    previous = candles[-2]

    orders = []

    # --------------------------------------------------------
    # BUY STOP
    # --------------------------------------------------------

    buy_stop_entry = (
        max(
            last["high"],
            previous["high"]
        )
        + atr * 0.10
    )

    buy_stop_sl = (
        buy_stop_entry
        - atr * 1.5
    )

    buy_stop_tp1 = (
        buy_stop_entry
        + atr * 1.5
    )

    buy_stop_tp2 = (
        buy_stop_entry
        + atr * 2.5
    )

    buy_stop_tp3 = (
        buy_stop_entry
        + atr * 4
    )

    # --------------------------------------------------------
    # SELL STOP
    # --------------------------------------------------------

    sell_stop_entry = (
        min(
            last["low"],
            previous["low"]
        )
        - atr * 0.10
    )

    sell_stop_sl = (
        sell_stop_entry
        + atr * 1.5
    )

    sell_stop_tp1 = (
        sell_stop_entry
        - atr * 1.5
    )

    sell_stop_tp2 = (
        sell_stop_entry
        - atr * 2.5
    )

    sell_stop_tp3 = (
        sell_stop_entry
        - atr * 4
    )

    # --------------------------------------------------------
    # BUY LIMIT
    # --------------------------------------------------------

    buy_limit_entry = (
        last["close"]
        - atr * 0.50
    )

    buy_limit_sl = (
        buy_limit_entry
        - atr * 1.5
    )

    buy_limit_tp1 = (
        buy_limit_entry
        + atr * 1.5
    )

    buy_limit_tp2 = (
        buy_limit_entry
        + atr * 2.5
    )

    buy_limit_tp3 = (
        buy_limit_entry
        + atr * 4
    )

    # --------------------------------------------------------
    # SELL LIMIT
    # --------------------------------------------------------

    sell_limit_entry = (
        last["close"]
        + atr * 0.50
    )

    sell_limit_sl = (
        sell_limit_entry
        + atr * 1.5
    )

    sell_limit_tp1 = (
        sell_limit_entry
        - atr * 1.5
    )

    sell_limit_tp2 = (
        sell_limit_entry
        - atr * 2.5
    )

    sell_limit_tp3 = (
        sell_limit_entry
        - atr * 4
    )

    if signal == "BUY":

        orders.append(
            {
                "type": "BUY STOP",
                "entry": buy_stop_entry,
                "sl": buy_stop_sl,
                "tp1": buy_stop_tp1,
                "tp2": buy_stop_tp2,
                "tp3": buy_stop_tp3
            }
        )

        orders.append(
            {
                "type": "BUY LIMIT",
                "entry": buy_limit_entry,
                "sl": buy_limit_sl,
                "tp1": buy_limit_tp1,
                "tp2": buy_limit_tp2,
                "tp3": buy_limit_tp3
            }
        )

    elif signal == "SELL":

        orders.append(
            {
                "type": "SELL STOP",
                "entry": sell_stop_entry,
                "sl": sell_stop_sl,
                "tp1": sell_stop_tp1,
                "tp2": sell_stop_tp2,
                "tp3": sell_stop_tp3
            }
        )

        orders.append(
            {
                "type": "SELL LIMIT",
                "entry": sell_limit_entry,
                "sl": sell_limit_sl,
                "tp1": sell_limit_tp1,
                "tp2": sell_limit_tp2,
                "tp3": sell_limit_tp3
            }
        )

    return orders


# ============================================================
# GOLD AI ANALYSIS
# ============================================================

def analyze_gold():

    candles, error = get_candles(
        MAIN_INTERVAL,
        OUTPUT_SIZE
    )

    if error:
        return None, error

    if len(candles) < 60:

        return None, (
            "Not enough 15-minute "
            "candle data."
        )

    closes = [
        candle["close"]
        for candle in candles
    ]

    price = closes[-1]

    ema20 = calculate_ema(
        closes,
        20
    )

    ema50 = calculate_ema(
        closes,
        50
    )

    rsi = calculate_rsi(
        closes,
        14
    )

    atr = calculate_atr(
        candles,
        14
    )

    if None in (
        ema20,
        ema50,
        rsi,
        atr
    ):

        return None, (
            "Unable to calculate "
            "indicators."
        )

    # ========================================================
    # HIGHER TIMEFRAME
    # ========================================================

    htf_candles, htf_error = (
        get_candles(
            HTF_INTERVAL,
            100
        )
    )

    entry_candles, entry_error = (
        get_candles(
            ENTRY_INTERVAL,
            100
        )
    )

    if not htf_error:

        htf_trend = timeframe_trend(
            htf_candles
        )

    else:

        htf_trend = "UNKNOWN"

    if not entry_error:

        entry_trend = timeframe_trend(
            entry_candles
        )

    else:

        entry_trend = "UNKNOWN"

    # ========================================================
    # STRUCTURE
    # ========================================================

    structure = market_structure(
        candles
    )

    structure_trend = trend_structure(
        candles
    )

    sweep = liquidity_sweep(
        candles
    )

    fvg = fair_value_gap(
        candles
    )

    last_candle = candles[-1]

    score = 0

    reasons = []

    warnings = []

    # ========================================================
    # EMA TREND
    # ========================================================

    if price > ema20:

        score += 1

        reasons.append(
            "Price above EMA20"
        )

    else:

        score -= 1

    if ema20 > ema50:

        score += 2

        reasons.append(
            "EMA20 above EMA50"
        )

    else:

        score -= 2

    # ========================================================
    # RSI
    # ========================================================

    if 55 <= rsi <= 68:

        score += 2

        reasons.append(
            "Bullish RSI momentum"
        )

    elif 32 <= rsi <= 45:

        score -= 2

        reasons.append(
            "Bearish RSI momentum"
        )

    elif rsi > 72:

        score -= 2

        warnings.append(
            "RSI overbought"
        )

    elif rsi < 28:

        score += 1

        warnings.append(
            "RSI oversold"
        )

    else:

        warnings.append(
            "RSI neutral"
        )

    # ========================================================
    # ATR
    # ========================================================

    if atr >= 4:

        reasons.append(
            "Healthy GOLD volatility"
        )

    else:

        score -= 2

        warnings.append(
            "Low volatility"
        )

    # ========================================================
    # CANDLE
    # ========================================================

    if bullish_engulfing(
        candles
    ):

        score += 2

        reasons.append(
            "Bullish engulfing"
        )

    elif bearish_engulfing(
        candles
    ):

        score -= 2

        reasons.append(
            "Bearish engulfing"
        )

    elif strong_bullish_candle(
        last_candle
    ):

        score += 1

        reasons.append(
            "Strong bullish candle"
        )

    elif strong_bearish_candle(
        last_candle
    ):

        score -= 1

        reasons.append(
            "Strong bearish candle"
        )

    else:

        warnings.append(
            "Weak candle confirmation"
        )

    # ========================================================
    # MARKET STRUCTURE
    # ========================================================

    if structure == "BOS_BUY":

        score += 3

        reasons.append(
            "Bullish Break of Structure"
        )

    elif structure == "BOS_SELL":

        score -= 3

        reasons.append(
            "Bearish Break of Structure"
        )

    # ========================================================
    # LIQUIDITY
    # ========================================================

    if sweep == "BUY_SWEEP":

        score += 1

        reasons.append(
            "Buy-side liquidity sweep"
        )

    elif sweep == "SELL_SWEEP":

        score -= 1

        reasons.append(
            "Sell-side liquidity sweep"
        )

    # ========================================================
    # FVG
    # ========================================================

    if fvg == "BULL":

        score += 1

        reasons.append(
            "Bullish FVG"
        )

    elif fvg == "BEAR":

        score -= 1

        reasons.append(
            "Bearish FVG"
        )

    # ========================================================
    # 1H
    # ========================================================

    if htf_trend == "BULLISH":

        score += 3

        reasons.append(
            "1H bullish confirmation"
        )

    elif htf_trend == "BEARISH":

        score -= 3

        reasons.append(
            "1H bearish confirmation"
        )

    else:

        warnings.append(
            "1H trend mixed"
        )

    # ========================================================
    # 5M
    # ========================================================

    if entry_trend == "BULLISH":

        score += 2

        reasons.append(
            "5M bullish confirmation"
        )

    elif entry_trend == "BEARISH":

        score -= 2

        reasons.append(
            "5M bearish confirmation"
        )

    else:

        warnings.append(
            "5M trend mixed"
        )

    # ========================================================
    # SESSION
    # ========================================================

    active_session = kill_zone()

    if active_session:

        reasons.append(
            "Active London/New York session"
        )

    else:

        score -= 1

        warnings.append(
            "Outside preferred session"
        )

    # ========================================================
    # RAW SIGNAL
    # ========================================================

    if score >= SIGNAL_SCORE:

        signal = "BUY"
        icon = "🟢"

    elif score <= -SIGNAL_SCORE:

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

            warnings.append(
                "1H conflicts with BUY"
            )

        if entry_trend == "BEARISH":

            signal = "WAIT"
            icon = "🟡"

            warnings.append(
                "5M conflicts with BUY"
            )

    elif signal == "SELL":

        if htf_trend == "BULLISH":

            signal = "WAIT"
            icon = "🟡"

            warnings.append(
                "1H conflicts with SELL"
            )

        if entry_trend == "BULLISH":

            signal = "WAIT"
            icon = "🟡"

            warnings.append(
                "5M conflicts with SELL"
            )

    # ========================================================
    # SIGNAL STRENGTH
    # ========================================================

    confidence = min(
        99,
        max(
            35,
            50 + abs(score) * 4
        )
    )

    # ========================================================
    # RISK LEVELS
    # ========================================================

    entry = price

    stop_loss = None
    tp1 = None
    tp2 = None
    tp3 = None

    if signal == "BUY":

        stop_loss = (
            entry
            - atr * 1.5
        )

        tp1 = (
            entry
            + atr * 1.5
        )

        tp2 = (
            entry
            + atr * 2.5
        )

        tp3 = (
            entry
            + atr * 4
        )

    elif signal == "SELL":

        stop_loss = (
            entry
            + atr * 1.5
        )

        tp1 = (
            entry
            - atr * 1.5
        )

        tp2 = (
            entry
            - atr * 2.5
        )

        tp3 = (
            entry
            - atr * 4
        )

    pending_orders = (
        build_pending_orders(
            candles,
            atr,
            signal
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

        "score": score,
        "confidence": confidence,

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

        "pending_orders": pending_orders,

        "candle_time": candles[-1][
            "datetime"
        ]

    }, None


# ============================================================
# TRADE CHECK
# ============================================================

def market_trade_exists(
    side
):

    for trade in open_trades:

        if (
            trade.get("status")
            == "OPEN"
            and trade.get("type")
            == "MARKET"
            and trade.get("side")
            == side
        ):

            return True

    return False


def pending_trade_exists(
    order_type,
    entry
):

    for trade in open_trades:

        if (
            trade.get("status")
            == "PENDING"
            and trade.get("type")
            == order_type
        ):

            if abs(
                trade.get("entry", 0)
                - entry
            ) < 0.20:

                return True

    return False


# ============================================================
# CREATE MARKET TRADE
# ============================================================

def create_market_trade(
    result
):

    global last_signal_key

    if result["signal"] == "WAIT":
        return False

    if (
        result["confidence"]
        < MIN_CONFIDENCE
    ):

        return False

    signal_key = (
        "MARKET",
        result["signal"],
        result["candle_time"]
    )

    if signal_key == last_signal_key:
        return False

    if market_trade_exists(
        result["signal"]
    ):

        return False

    trade = {

        "id": int(
            time.time() * 1000
        ),

        "symbol": XAU_SYMBOL,

        "type": "MARKET",

        "side": result["signal"],

        "entry": result["entry"],

        "sl": result["stop_loss"],

        "initial_sl": result[
            "stop_loss"
        ],

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

    open_trades.append(
        trade
    )

    last_signal_key = (
        signal_key
    )

    save_trades()

    return True


# ============================================================
# CREATE PENDING TRADE
# ============================================================

def create_pending_trade(
    order
):

    if pending_trade_exists(
        order["type"],
        order["entry"]
    ):

        return False

    trade = {

        "id": int(
            time.time() * 1000
        ),

        "symbol": XAU_SYMBOL,

        "type": order["type"],

        "side": (
            "BUY"
            if "BUY"
            in order["type"]
            else "SELL"
        ),

        "entry": order["entry"],

        "sl": order["sl"],

        "initial_sl": order["sl"],

        "tp1": order["tp1"],

        "tp2": order["tp2"],

        "tp3": order["tp3"],

        "tp1_hit": False,

        "tp2_hit": False,

        "tp3_hit": False,

        "break_even": False,

        "status": "PENDING",

        "created_at": datetime.now(
            timezone.utc
        ).isoformat()
    }

    open_trades.append(
        trade
    )

    save_trades()

    return True


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

async def send_chat_message(
    context,
    text
):

    if not CHAT_ID:

        logger.warning(
            "CHAT_ID is missing."
        )

        return False

    try:

        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=text,
            parse_mode="Markdown"
        )

        return True

    except Exception as error:

        logger.error(
            "Telegram send error: %s",
            error
        )

        return False


# ============================================================
# FORMAT PENDING ORDER
# ============================================================

def format_pending_order(
    order
):

    return (
        f"📌 *{order['type']}*\n"
        f"Entry: `${order['entry']:,.2f}`\n"
        f"SL: `${order['sl']:,.2f}`\n"
        f"TP1: `${order['tp1']:,.2f}`\n"
        f"TP2: `${order['tp2']:,.2f}`\n"
        f"TP3: `${order['tp3']:,.2f}`\n"
    )


# ============================================================
# FORMAT ANALYSIS
# ============================================================

def format_analysis(
    result
):

    message = (

        "👑 *KING OF XAU_NAS — "
        "INSTITUTIONAL AI* 👑\n\n"

        "🟡 *XAU/USD GOLD*\n\n"

        f"💰 Price: "
        f"`${result['price']:,.2f}`\n"

        f"📈 Structure: "
        f"*{result['trend']}*\n"

        f"🧠 AI Score: "
        f"`{result['score']}`\n"

        f"💪 Signal Strength: "
        f"`{result['confidence']}%`\n\n"

        "━━━━━━━━━━━━━━━━━━\n"

        "📊 *MULTI-TIMEFRAME*\n"

        "━━━━━━━━━━━━━━━━━━\n\n"

        f"1H Trend: "
        f"*{result['htf_trend']}*\n"

        f"15M Setup: "
        f"*{result['trend']}*\n"

        f"5M Entry: "
        f"*{result['entry_trend']}*\n\n"

        "━━━━━━━━━━━━━━━━━━\n"

        "📊 *TECHNICAL ENGINE*\n"

        "━━━━━━━━━━━━━━━━━━\n\n"

        f"EMA 20: "
        f"`{result['ema20']:,.2f}`\n"

        f"EMA 50: "
        f"`{result['ema50']:,.2f}`\n"

        f"RSI 14: "
        f"`{result['rsi']:.1f}`\n"

        f"ATR 14: "
        f"`{result['atr']:.2f}`\n"

        f"BOS: "
        f"`{result['structure']}`\n"

        f"Liquidity: "
        f"`{result['sweep']}`\n"

        f"FVG: "
        f"`{result['fvg']}`\n\n"

        "━━━━━━━━━━━━━━━━━━\n"

        "🎯 *SIGNAL*\n"

        "━━━━━━━━━━━━━━━━━━\n\n"

        f"{result['icon']} "
        f"Signal: *{result['signal']}*\n"

        f"🧠 Strength: "
        f"`{result['confidence']}%`\n"
    )

    if result["signal"] != "WAIT":

        message += (

            "\n"

            f"🎯 Entry: "
            f"`${result['entry']:,.2f}`\n"

            f"🛑 SL: "
            f"`${result['stop_loss']:,.2f}`\n"

            f"🎯 TP1: "
            f"`${result['tp1']:,.2f}`\n"

            f"🎯 TP2: "
            f"`${result['tp2']:,.2f}`\n"

            f"🏆 TP3: "
            f"`${result['tp3']:,.2f}`\n"
        )

        if result[
            "pending_orders"
        ]:

            message += (
                "\n📌 *PENDING SETUPS*\n"
            )

            for order in result[
                "pending_orders"
            ]:

                message += (
                    "\n"
                    + format_pending_order(
                        order
                    )
                )

    else:

        message += (

            "\n"

            "⏳ *WAIT — "
            "NO ELITE SETUP*\n"

            "The filters are not "
            "sufficiently aligned.\n"
        )

    if result["reasons"]:

        message += (
            "\n🧠 *CONFIRMATIONS*\n"
        )

        for reason in result[
            "reasons"
        ][:10]:

            message += (
                f"✅ {reason}\n"
            )

    if result["warnings"]:

        message += (
            "\n⚠️ *WARNINGS*\n"
        )

        for warning in result[
            "warnings"
        ][:7]:

            message += (
                f"• {warning}\n"
            )

    message += (

        "\n━━━━━━━━━━━━━━━━━━\n"

        f"⏱️ Timeframe: "
        f"*{MAIN_INTERVAL}*\n"

        "📡 Data: Twelve Data\n"

        "📲 Alerts: Telegram only\n\n"

        "⚠️ Signal strength is NOT "
        "guaranteed win probability.\n"

        "⚠️ Analysis only — "
        "not financial advice.\n"

        "⚠️ No broker orders are placed."
    )

    return message


# ============================================================
# AUTOMATIC SIGNAL ALERT
# ============================================================

def format_signal_alert(
    result
):

    message = (

        "🚨 *NEW KING OF XAU_NAS SIGNAL* 🚨\n\n"

        f"{result['icon']} "
        f"*{result['signal']} XAU/USD*\n\n"

        f"💰 Entry: "
        f"`${result['entry']:,.2f}`\n"

        f"🛑 SL: "
        f"`${result['stop_loss']:,.2f}`\n"

        f"🎯 TP1: "
        f"`${result['tp1']:,.2f}`\n"

        f"🎯 TP2: "
        f"`${result['tp2']:,.2f}`\n"

        f"🏆 TP3: "
        f"`${result['tp3']:,.2f}`\n\n"

        f"🧠 Strength: "
        f"`{result['confidence']}%`\n"

        f"📊 Score: "
        f"`{result['score']}`\n\n"

        f"1H: `{result['htf_trend']}`\n"

        f"15M: `{result['trend']}`\n"

        f"5M: `{result['entry_trend']}`\n"
    )

    if result[
        "pending_orders"
    ]:

        message += (
            "\n📌 *PENDING ORDER ALERTS*\n"
        )

        for order in result[
            "pending_orders"
        ]:

            message += (
                "\n"
                + format_pending_order(
                    order
                )
            )

    message += (

        "\n━━━━━━━━━━━━━━━━━━\n"

        "📲 Telegram signal only\n"

        "⚠️ No broker order has "
        "been placed.\n"

        "⚠️ Always manage risk."
    )

    return message


# ============================================================
# ACTIVATE PENDING ORDER
# ============================================================

def activate_pending(
    trade,
    price
):

    if trade.get(
        "status"
    ) != "PENDING":

        return False

    order_type = trade["type"]

    entry = trade["entry"]

    activated = False

    if (
        order_type == "BUY STOP"
        and price >= entry
    ):

        activated = True

    elif (
        order_type == "BUY LIMIT"
        and price <= entry
    ):

        activated = True

    elif (
        order_type == "SELL STOP"
        and price <= entry
    ):

        activated = True

    elif (
        order_type == "SELL LIMIT"
        and price >= entry
    ):

        activated = True

    if activated:

        trade["status"] = "OPEN"

        trade["activation_price"] = price

        trade["activated_at"] = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        return True

    return False


# ============================================================
# TRADE MONITOR
# ============================================================

async def monitor_trades(
    context
):

    logger.info(
        "Trade monitor started."
    )

    while True:

        try:

            price, error = get_price()

            if (
                error
                or price is None
            ):

                await asyncio.sleep(
                    MONITOR_SECONDS
                )

                continue

            changed = False

            for trade in open_trades:

                # ==================================================
                # PENDING
                # ==================================================

                if trade.get(
                    "status"
                ) == "PENDING":

                    if activate_pending(
                        trade,
                        price
                    ):

                        changed = True

                        await send_chat_message(
                            context,
                            (
                                "⚡ *PENDING "
                                "ORDER ACTIVATED*\n\n"

                                "🟡 XAU/USD\n"

                                f"📌 "
                                f"{trade['type']}\n"

                                f"💰 Activation: "
                                f"`${price:,.2f}`\n"

                                f"🛑 SL: "
                                f"`${trade['sl']:,.2f}`\n"

                                f"🎯 TP1: "
                                f"`${trade['tp1']:,.2f}`"
                            )
                        )

                # ==================================================
                # ONLY OPEN TRADES
                # ==================================================

                if trade.get(
                    "status"
                ) != "OPEN":

                    continue

                side = trade["side"]

                # ==================================================
                # TP1
                # ==================================================

                if not trade[
                    "tp1_hit"
                ]:

                    tp1_reached = (

                        price
                        >= trade["tp1"]

                        if side == "BUY"

                        else

                        price
                        <= trade["tp1"]
                    )

                    if tp1_reached:

                        trade[
                            "tp1_hit"
                        ] = True

                        trade[
                            "sl"
                        ] = trade[
                            "entry"
                        ]

                        trade[
                            "break_even"
                        ] = True

                        changed = True

                        await send_chat_message(
                            context,
                            (
                                f"🎯 *TP1 HIT — "
                                f"{side}*\n\n"

                                "🟡 XAU/USD\n"

                                f"💰 Price: "
                                f"`${price:,.2f}`\n"

                                "🛡️ SL moved "
                                "to BREAK-EVEN."
                            )
                        )

                # ==================================================
                # TP2
                # ==================================================

                if (
                    trade["tp1_hit"]
                    and not trade[
                        "tp2_hit"
                    ]
                ):

                    tp2_reached = (

                        price
                        >= trade["tp2"]

                        if side == "BUY"

                        else

                        price
                        <= trade["tp2"]
                    )

                    if tp2_reached:

                        trade[
                            "tp2_hit"
                        ] = True

                        if side == "BUY":

                            trade[
                                "sl"
                            ] = max(
                                trade["sl"],
                                trade["tp1"]
                            )

                        else:

                            trade[
                                "sl"
                            ] = min(
                                trade["sl"],
                                trade["tp1"]
                            )

                        changed = True

                        await send_chat_message(
                            context,
                            (
                                f"🏆 *TP2 HIT — "
                                f"{side}*\n\n"

                                f"💰 Price: "
                                f"`${price:,.2f}`\n"

                                f"🛡️ Protected SL: "
                                f"`${trade['sl']:,.2f}`\n"

                                "📈 Trailing "
                                "protection active."
                            )
                        )

                # ==================================================
                # TRAILING
                # ==================================================

                if (
                    trade["tp2_hit"]
                    and not trade[
                        "tp3_hit"
                    ]
                ):

                    distance = (
                        abs(
                            trade["tp3"]
                            - trade["tp2"]
                        )
                        * 0.50
                    )

                    if side == "BUY":

                        new_sl = (
                            price
                            - distance
                        )

                        if (
                            new_sl
                            > trade["sl"]
                        ):

                            trade[
                                "sl"
                            ] = new_sl

                            changed = True

                    else:

                        new_sl = (
                            price
                            + distance
                        )

                        if (
                            new_sl
                            < trade["sl"]
                        ):

                            trade[
                                "sl"
                            ] = new_sl

                            changed = True

                # ==================================================
                # TP3
                # ==================================================

                if not trade[
                    "tp3_hit"
                ]:

                    tp3_reached = (

                        price
                        >= trade["tp3"]

                        if side == "BUY"

                        else

                        price
                        <= trade["tp3"]
                    )

                                        if tp3_reached:

                        trade[
                            "tp3_hit"
                        ] = True

                        trade[
                            "status"
                        ] = "TP3"

                        trade[
                            "exit_price"
                        ] = price

                        trade[
                            "closed_at"
                        ] = (
                            datetime.now(
                                timezone.utc
                            ).isoformat()
                        )

                        changed = True

                        await send_chat_message(
                            context,
                            (
                                "👑 *TP3 HIT — TRADE COMPLETE*\n\n"
                                f"🟡 XAU/USD {side}\n"
                                f"💰 Exit: `${price:,.2f}`\n"
                                "🏆 Full target reached.\n"
                                "✅ Trade closed successfully."
                            )
                        )
