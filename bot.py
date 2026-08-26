import os
import time
import asyncio
import threading
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ============================================================
# 👑 KING GOLD SCALPER
# XAU/USD SIGNAL-ONLY TRADING BOT
#
# Features:
# - Normal BUY / SELL scalping
# - BUY STOP / SELL STOP
# - Breakout Radar
# - Slingshot
# - Market Mood
# - Anti-repeat protection
# - Signal expiry
# - 1M / 5M / 15M analysis
# - Twelve Data
# - Telegram
# - Render health server
#
# IMPORTANT:
# This version generates SIGNALS only.
# It does NOT place MT5 orders automatically.
# ============================================================


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TWELVE_API_KEY = os.getenv(
    "TWELVE_DATA_API_KEY",
    ""
).strip()

PORT = int(
    os.getenv(
        "PORT",
        "10000"
    )
)

SYMBOL = "XAU/USD"

SCAN_SECONDS = 60

OUTPUT_SIZE = 100

# ============================================================
# INDICATORS
# ============================================================

EMA_FAST = 9
EMA_MID = 21
EMA_SLOW = 50

RSI_PERIOD = 14
ATR_PERIOD = 14

MIN_CONFIDENCE = 60

# ============================================================
# ANTI-REPEAT
# ============================================================

SIGNAL_COOLDOWN = 180

MIN_NEW_SETUP_DISTANCE = 1.00

MIN_NEW_SETUP_ATR = 0.75

# ============================================================
# PENDING ORDER SETTINGS
# ============================================================

PENDING_BUFFER_ATR = 0.25

PENDING_SL_ATR = 1.40

PENDING_TP1_ATR = 1.50

PENDING_TP2_ATR = 2.30

# ============================================================
# SIGNAL EXPIRY
# ============================================================

SIGNAL_EXPIRY_MINUTES = 15

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(
    "KING_GOLD_SCALPER"
)


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():

    return jsonify({
        "bot": "KING GOLD SCALPER",
        "status": "running",
        "market": SYMBOL,
        "mode": "SIGNAL ONLY",
        "features": [
            "SCALPING",
            "BUY STOP",
            "SELL STOP",
            "BREAKOUT RADAR",
            "SLINGSHOT",
            "MARKET MOOD",
        ],
        "server_time": datetime.now(
            timezone.utc
        ).isoformat()
    })


@app.route("/health")
def health():

    return jsonify({
        "status": "OK",
        "bot": "KING GOLD SCALPER",
        "scanner": "RUNNING",
        "market": SYMBOL
    })


def run_web_server():

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )


# ============================================================
# GLOBAL STATE
# ============================================================

subscribers = set()

last_price = None
last_scan_time = None

scanner_running = True

state_lock = threading.Lock()

# ============================================================
# LAST AUTOMATIC SIGNAL
# ============================================================

last_auto_signal = {
    "type": None,
    "direction": None,
    "entry": None,
    "atr": None,
    "trend_5m": None,
    "trend_15m": None,
    "rsi_zone": None,
    "time": 0,
}


# ============================================================
# ACTIVE SIGNALS
# ============================================================

active_signals = []


# ============================================================
# TELEGRAM MENU
# ============================================================

def main_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "🟢 SCALP BUY",
                callback_data="buy"
            ),
            InlineKeyboardButton(
                "🔴 SCALP SELL",
                callback_data="sell"
            ),
        ],

        [
            InlineKeyboardButton(
                "🟢 BUY STOP",
                callback_data="buystop"
            ),
            InlineKeyboardButton(
                "🔴 SELL STOP",
                callback_data="sellstop"
            ),
        ],

        [
            InlineKeyboardButton(
                "🏹 SLINGSHOT",
                callback_data="slingshot"
            ),
        ],

        [
            InlineKeyboardButton(
                "💥 BREAKOUT RADAR",
                callback_data="breakout"
            ),
        ],

        [
            InlineKeyboardButton(
                "⚡ AUTO SCALPING",
                callback_data="auto"
            ),
        ],

        [
            InlineKeyboardButton(
                "📊 SCAN NOW",
                callback_data="scan"
            ),
            InlineKeyboardButton(
                "🧠 MARKET MOOD",
                callback_data="mood"
            ),
        ],

        [
            InlineKeyboardButton(
                "📡 LIVE SIGNAL",
                callback_data="live"
            ),
            InlineKeyboardButton(
                "❤️ STATUS",
                callback_data="status"
            ),
        ],

        [
            InlineKeyboardButton(
                "⛔ STOP ALERTS",
                callback_data="stop"
            )
        ]
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# WELCOME
# ============================================================

def welcome_message():

    return (
        "👑 *KING GOLD SCALPER*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🟡 *XAU/USD SIGNAL SYSTEM*\n\n"

        "⚡ Normal scalping\n"
        "🟢 BUY STOP\n"
        "🔴 SELL STOP\n"
        "🏹 Slingshot\n"
        "💥 Breakout Radar\n"
        "🧠 Market Mood\n\n"

        "📉 Entry: 1M\n"
        "📊 Confirmation: 5M\n"
        "📈 Trend: 15M\n\n"

        "Indicators:\n"
        "• EMA 9 / 21 / 50\n"
        "• RSI 14\n"
        "• ATR 14\n"
        "• Momentum\n"
        "• Structure\n\n"

        "🛡 Anti-repeat protection\n"
        "⏰ Signal expiry\n\n"

        "Select an option:"
    )


# ============================================================
# TWELVE DATA
# ============================================================

def get_candles(interval):

    if not TWELVE_API_KEY:

        logger.error(
            "TWELVE_DATA_API_KEY missing."
        )

        return []

    url = (
        "https://api.twelvedata.com/"
        "time_series"
    )

    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "outputsize": OUTPUT_SIZE,
        "apikey": TWELVE_API_KEY,
        "format": "JSON"
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=15
        )

        if response.status_code != 200:

            logger.error(
                "Twelve Data HTTP %s",
                response.status_code
            )

            return []

        data = response.json()

        if "values" not in data:

            logger.error(
                "Twelve Data error: %s",
                data.get(
                    "message",
                    data
                )
            )

            return []

        candles = []

        for row in reversed(
            data["values"]
        ):

            try:

                candles.append({
                    "datetime": row[
                        "datetime"
                    ],
                    "open": float(
                        row["open"]
                    ),
                    "high": float(
                        row["high"]
                    ),
                    "low": float(
                        row["low"]
                    ),
                    "close": float(
                        row["close"]
                    ),
                })

            except Exception:
                continue

        return candles

    except Exception as e:

        logger.error(
            "Market data error: %s",
            e
        )

        return []


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = (
        2 / (period + 1)
    )

    result = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        result = (
            (price - result)
            * multiplier
        ) + result

    return result


# ============================================================
# RSI
# ============================================================

def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = (
            values[i]
            - values[i - 1]
        )

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# ATR
# ============================================================

def atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(
        1,
        len(candles)
    ):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(

            current["high"]
            - current["low"],

            abs(
                current["high"]
                - previous["close"]
            ),

            abs(
                current["low"]
                - previous["close"]
            )
        )

        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    value = (
        sum(
            true_ranges[:period]
        )
        / period
    )

    for tr in true_ranges[period:]:

        value = (
            (
                value
                * (period - 1)
            )
            + tr
        ) / period

    return value


# ============================================================
# RSI ZONE
# ============================================================

def rsi_zone(value):

    if value is None:
        return "UNKNOWN"

    if value >= 70:
        return "OVERBOUGHT"

    if value >= 55:
        return "BULLISH"

    if value >= 45:
        return "NEUTRAL"

    if value >= 30:
        return "BEARISH"

    return "OVERSOLD"


# ============================================================
# TIMEFRAME ANALYSIS
# ============================================================

def analyze_timeframe(candles):

    if len(candles) < 60:
        return None

    closes = [
        c["close"]
        for c in candles
    ]

    current = candles[-1]
    previous = candles[-2]

    price = current["close"]

    ema9 = ema(
        closes,
        EMA_FAST
    )

    ema21 = ema(
        closes,
        EMA_MID
    )

    ema50 = ema(
        closes,
        EMA_SLOW
    )

    rsi_value = rsi(
        closes,
        RSI_PERIOD
    )

    atr_value = atr(
        candles,
        ATR_PERIOD
    )

    if None in (
        ema9,
        ema21,
        ema50,
        rsi_value,
        atr_value
    ):
        return None

    buy_score = 0
    sell_score = 0

    # EMA
    if ema9 > ema21:
        buy_score += 2

    elif ema9 < ema21:
        sell_score += 2

    # EMA50
    if price > ema50:
        buy_score += 2

    elif price < ema50:
        sell_score += 2

    # Candle
    if current["close"] > current["open"]:
        buy_score += 1

    elif current["close"] < current["open"]:
        sell_score += 1

    # Momentum
    if current["close"] > previous["close"]:
        buy_score += 1

    elif current["close"] < previous["close"]:
        sell_score += 1

    # RSI
    if 52 <= rsi_value <= 70:
        buy_score += 2

    if 30 <= rsi_value <= 48:
        sell_score += 2

    # Extreme protection
    if rsi_value > 75:
        buy_score -= 1

    if rsi_value < 25:
        sell_score -= 1

    if buy_score > sell_score:

        direction = "BUY"
        score = buy_score

    elif sell_score > buy_score:

        direction = "SELL"
        score = sell_score

    else:

        direction = "NEUTRAL"
        score = 0

    return {
        "direction": direction,
        "score": score,
        "price": price,
        "ema9": ema9,
        "ema21": ema21,
        "ema50": ema50,
        "rsi": rsi_value,
        "atr": atr_value,
        "high": current["high"],
        "low": current["low"],
        "open": current["open"],
        "close": current["close"],
    }


# ============================================================
# GET ALL MARKET ANALYSIS
# ============================================================

def get_market_analysis():

    candles_1m = get_candles(
        "1min"
    )

    candles_5m = get_candles(
        "5min"
    )

    candles_15m = get_candles(
        "15min"
    )

    if not candles_1m:
        return None

    if not candles_5m:
        return None

    if not candles_15m:
        return None

    a1 = analyze_timeframe(
        candles_1m
    )

    a5 = analyze_timeframe(
        candles_5m
    )

    a15 = analyze_timeframe(
        candles_15m
    )

    if not a1 or not a5 or not a15:
        return None

    return {
        "1m": a1,
        "5m": a5,
        "15m": a15,
        "candles_1m": candles_1m,
        "candles_5m": candles_5m,
        "candles_15m": candles_15m,
    }


# ============================================================
# NORMAL SCALP SIGNAL
# ============================================================

def generate_scalp_signal():

    global last_price
    global last_scan_time

    market = get_market_analysis()

    if not market:
        return None

    a1 = market["1m"]
    a5 = market["5m"]
    a15 = market["15m"]

    price = a1["price"]

    last_price = price

    last_scan_time = datetime.now(
        timezone.utc
    )

    buy_points = 0
    sell_points = 0

    if a1["direction"] == "BUY":
        buy_points += 4

    elif a1["direction"] == "SELL":
        sell_points += 4

    if a5["direction"] == "BUY":
        buy_points += 3

    elif a5["direction"] == "SELL":
        sell_points += 3

    if a15["direction"] == "BUY":
        buy_points += 2

    elif a15["direction"] == "SELL":
        sell_points += 2

    if buy_points > sell_points:

        if buy_points < 5:
            return None

        direction = "BUY"

        confidence = min(
            95,
            55 + buy_points * 4
        )

    elif sell_points > buy_points:

        if sell_points < 5:
            return None

        direction = "SELL"

        confidence = min(
            95,
            55 + sell_points * 4
        )

    else:

        return None

    atr_value = a1["atr"]

    if atr_value <= 0:
        return None

    sl_distance = (
        atr_value * 1.4
    )

    tp1_distance = (
        atr_value * 1.5
    )

    tp2_distance = (
        atr_value * 2.3
    )

    if direction == "BUY":

        entry = price

        stop_loss = (
            entry - sl_distance
        )

        tp1 = (
            entry + tp1_distance
        )

        tp2 = (
            entry + tp2_distance
        )

    else:

        entry = price

        stop_loss = (
            entry + sl_distance
        )

        tp1 = (
            entry - tp1_distance
        )

        tp2 = (
            entry - tp2_distance
        )

    return {
        "type": "SCALP",
        "symbol": SYMBOL,
        "direction": direction,
        "confidence": confidence,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "atr": atr_value,
        "rsi": a1["rsi"],
        "ema9": a1["ema9"],
        "ema21": a1["ema21"],
        "ema50": a1["ema50"],
        "trend_5m": a5["direction"],
        "trend_15m": a15["direction"],
    }


# ============================================================
# BREAKOUT RADAR
# ============================================================

def generate_breakout_signal():

    market = get_market_analysis()

    if not market:
        return None

    a1 = market["1m"]
    a5 = market["5m"]
    a15 = market["15m"]

    candles = market[
        "candles_5m"
    ]

    if len(candles) < 20:
        return None

    recent = candles[-20:-1]

    resistance = max(
        c["high"]
        for c in recent
    )

    support = min(
        c["low"]
        for c in recent
    )

    price = a1["price"]

    atr_value = a1["atr"]

    if atr_value <= 0:
        return None

    buffer = (
        atr_value
        * PENDING_BUFFER_ATR
    )

    buy_stop = (
        resistance + buffer
    )

    sell_stop = (
        support - buffer
    )

    if a5["direction"] == "BUY":

        bias = "BULLISH"

    elif a5["direction"] == "SELL":

        bias = "BEARISH"

    else:

        bias = "NEUTRAL"

    return {
        "type": "BREAKOUT",
        "symbol": SYMBOL,
        "price": price,
        "resistance": resistance,
        "support": support,
        "buy_stop": buy_stop,
        "sell_stop": sell_stop,
        "atr": atr_value,
        "trend_5m": a5["direction"],
        "trend_15m": a15["direction"],
        "bias": bias,
    }


# ============================================================
# BUY STOP / SELL STOP
# ============================================================

def generate_pending_signal(
    direction
):

    market = get_market_analysis()

    if not market:
        return None

    a1 = market["1m"]
    a5 = market["5m"]
    a15 = market["15m"]

    candles = market[
        "candles_5m"
    ]

    if len(candles) < 20:
        return None

    recent = candles[-20:-1]

    resistance = max(
        c["high"]
        for c in recent
    )

    support = min(
        c["low"]
        for c in recent
    )

    atr_value = a1["atr"]

    if atr_value <= 0:
        return None

    buffer = (
        atr_value
        * PENDING_BUFFER_ATR
    )

    if direction == "BUY":

        entry = (
            resistance + buffer
        )

        stop_loss = (
            entry -
            atr_value *
            PENDING_SL_ATR
        )

        tp1 = (
            entry +
            atr_value *
            PENDING_TP1_ATR
        )

        tp2 = (
            entry +
            atr_value *
            PENDING_TP2_ATR
        )

        order_type = "BUY STOP"

        # Prefer bullish confirmation
        confidence = 70

        if a5["direction"] == "BUY":
            confidence += 8

        if a15["direction"] == "BUY":
            confidence += 8

    else:

        entry = (
            support - buffer
        )

        stop_loss = (
            entry +
            atr_value *
            PENDING_SL_ATR
        )

        tp1 = (
            entry -
            atr_value *
            PENDING_TP1_ATR
        )

        tp2 = (
            entry -
            atr_value *
            PENDING_TP2_ATR
        )

        order_type = "SELL STOP"

        confidence = 70

        if a5["direction"] == "SELL":
            confidence += 8

        if a15["direction"] == "SELL":
            confidence += 8

    confidence = min(
        95,
        confidence
    )

    return {
        "type": order_type,
        "symbol": SYMBOL,
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "atr": atr_value,
        "rsi": a1["rsi"],
        "trend_5m": a5["direction"],
        "trend_15m": a15["direction"],
        "resistance": resistance,
        "support": support,
        "confidence": confidence,
        "created": time.time(),
        "expires": (
            time.time()
            + SIGNAL_EXPIRY_MINUTES * 60
        ),
    }


# ============================================================
# SLINGSHOT
# ============================================================

def generate_slingshot():

    market = get_market_analysis()

    if not market:
        return None

    a1 = market["1m"]
    a5 = market["5m"]
    a15 = market["15m"]

    candles = market[
        "candles_1m"
    ]

    if len(candles) < 10:
        return None

    recent = candles[-8:]

    previous_low = min(
        c["low"]
        for c in recent[:-2]
    )

    previous_high = max(
        c["high"]
        for c in recent[:-2]
    )

    current = candles[-1]

    atr_value = a1["atr"]

    if atr_value <= 0:
        return None

    # ========================================================
    # BULLISH SLINGSHOT
    # Liquidity sweep below support +
    # bullish rejection +
    # momentum confirmation
    # ========================================================

    bullish_sweep = (
        current["low"]
        < previous_low
        and
        current["close"]
        > previous_low
    )

    bullish_candle = (
        current["close"]
        > current["open"]
    )

    bullish_momentum = (
        a1["direction"] == "BUY"
    )

    if (
        bullish_sweep
        and bullish_candle
        and bullish_momentum
    ):

        entry = current["close"]

        stop_loss = (
            current["low"]
            - atr_value * 0.25
        )

        tp1 = (
            entry +
            atr_value * 1.5
        )

        tp2 = (
            entry +
            atr_value * 2.5
        )

        confidence = 82

        if a5["direction"] == "BUY":
            confidence += 4

        if a15["direction"] == "BUY":
            confidence += 4

        return {
            "type": "SLINGSHOT",
            "symbol": SYMBOL,
            "direction": "BUY",
            "entry": entry,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "atr": atr_value,
            "rsi": a1["rsi"],
            "trend_5m": a5["direction"],
            "trend_15m": a15["direction"],
            "confidence": min(
                95,
                confidence
            ),
            "liquidity": "SWEEP BELOW LOW",
            "rejection": "BULLISH",
            "momentum": "BULLISH",
        }

    # ========================================================
    # BEARISH SLINGSHOT
    # ========================================================

    bearish_sweep = (
        current["high"]
        > previous_high
        and
        current["close"]
        < previous_high
    )

    bearish_candle = (
        current["close"]
        < current["open"]
    )

    bearish_momentum = (
        a1["direction"] == "SELL"
    )

    if (
        bearish_sweep
        and bearish_candle
        and bearish_momentum
    ):

        entry = current["close"]

        stop_loss = (
            current["high"]
            + atr_value * 0.25
        )

        tp1 = (
            entry -
            atr_value * 1.5
        )

        tp2 = (
            entry -
            atr_value * 2.5
        )

        confidence = 82

        if a5["direction"] == "SELL":
            confidence += 4

        if a15["direction"] == "SELL":
            confidence += 4

        return {
            "type": "SLINGSHOT",
            "symbol": SYMBOL,
            "direction": "SELL",
            "entry": entry,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "atr": atr_value,
            "rsi": a1["rsi"],
            "trend_5m": a5["direction"],
            "trend_15m": a15["direction"],
            "confidence": min(
                95,
                confidence
            ),
            "liquidity": "SWEEP ABOVE HIGH",
            "rejection": "BEARISH",
            "momentum": "BEARISH",
        }

    return None


# ============================================================
# MARKET MOOD
# ============================================================

def generate_market_mood():

    market = get_market_analysis()

    if not market:
        return None

    a1 = market["1m"]
    a5 = market["5m"]
    a15 = market["15m"]

    buy = 0
    sell = 0

    if a1["direction"] == "BUY":
        buy += 1

    elif a1["direction"] == "SELL":
        sell += 1

    if a5["direction"] == "BUY":
        buy += 2

    elif a5["direction"] == "SELL":
        sell += 2

    if a15["direction"] == "BUY":
        buy += 3

    elif a15["direction"] == "SELL":
        sell += 3

    if buy >= sell + 3:

        mood = "🟢 STRONGLY BULLISH"

    elif buy > sell:

        mood = "🟢 BULLISH"

    elif sell >= buy + 3:

        mood = "🔴 STRONGLY BEARISH"

    elif sell > buy:

        mood = "🔴 BEARISH"

    else:

        mood = "🟡 NEUTRAL / CHOPPY"

    atr_value = a1["atr"]

    if atr_value >= 3:

        volatility = "🔥 HIGH"

    elif atr_value >= 1.5:

        volatility = "⚡ MEDIUM"

    else:

        volatility = "🧊 LOW"

    return {
        "mood": mood,
        "volatility": volatility,
        "1m": a1["direction"],
        "5m": a5["direction"],
        "15m": a15["direction"],
        "rsi": a1["rsi"],
        "atr": atr_value,
    }


# ============================================================
# ANTI-REPEAT
# ============================================================

def should_send_signal(signal):

    global last_auto_signal

    now = time.time()

    signal_type = signal.get(
        "type"
    )

    direction = signal.get(
        "direction"
    )

    entry = signal.get(
        "entry"
    )

    atr_value = signal.get(
        "atr",
        0
    )

    previous_type = (
        last_auto_signal["type"]
    )

    previous_direction = (
        last_auto_signal["direction"]
    )

    previous_entry = (
        last_auto_signal["entry"]
    )

    previous_atr = (
        last_auto_signal["atr"]
        or 0
    )

    previous_time = (
        last_auto_signal["time"]
    )

    # ========================================================
    # FIRST SIGNAL
    # ========================================================

    if previous_type is None:

        return True

    # ========================================================
    # DIFFERENT SIGNAL TYPE
    # ========================================================

    if signal_type != previous_type:

        return True

    # ========================================================
    # DIRECTION CHANGE
    # ========================================================

    if direction != previous_direction:

        return True

    # ========================================================
    # COOLDOWN
    # ========================================================

    if (
        now - previous_time
        < SIGNAL_COOLDOWN
    ):

        return False

    # ========================================================
    # PRICE MOVEMENT
    # ========================================================

    if (
        previous_entry is not None
        and
        entry is not None
    ):

        movement = abs(
            entry -
            previous_entry
        )

        required = max(
            MIN_NEW_SETUP_DISTANCE,
            max(
                atr_value,
                previous_atr
            )
            * MIN_NEW_SETUP_ATR
        )

        if movement >= required:

            return True

    # ========================================================
    # OTHERWISE BLOCK
    # ========================================================

    return False


def remember_signal(signal):

    global last_auto_signal

    last_auto_signal = {
        "type": signal.get(
            "type"
        ),
        "direction": signal.get(
            "direction"
        ),
        "entry": signal.get(
            "entry"
        ),
        "atr": signal.get(
            "atr"
        ),
        "trend_5m": signal.get(
            "trend_5m"
        ),
        "trend_15m": signal.get(
            "trend_15m"
        ),
        "rsi_zone": rsi_zone(
            signal.get("rsi")
        ),
        "time": time.time(),
    }


# ============================================================
# ADD ACTIVE SIGNAL
# ============================================================

def add_active_signal(signal):

    if "expires" not in signal:

        signal["expires"] = (
            time.time()
            + SIGNAL_EXPIRY_MINUTES * 60
        )

    active_signals.append(
        signal
    )

    cleanup_active_signals()


# ============================================================
# CLEANUP EXPIRED SIGNALS
# ============================================================

def cleanup_active_signals():

    now = time.time()

    active_signals[:] = [
        s
        for s in active_signals
        if s.get(
            "expires",
            0
        ) > now
    ]


# ============================================================
# NORMAL SCALP MESSAGE
# ============================================================

def format_scalp(signal):

    if signal["direction"] == "BUY":

        emoji = "🟢"

    else:

        emoji = "🔴"

    return (
        "👑 *KING GOLD SCALPER*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"{emoji} *SCALP "
        f"{signal['direction']} XAU/USD*\n\n"

        f"💰 Entry: `{signal['entry']:.2f}`\n"
        f"🛑 SL: `{signal['stop_loss']:.2f}`\n"
        f"🎯 TP1: `{signal['tp1']:.2f}`\n"
        f"🎯 TP2: `{signal['tp2']:.2f}`\n\n"

        f"📊 Confidence: "
        f"*{signal['confidence']:.0f}%*\n"
        "⏱ Entry: *1M*\n"
        "📊 Confirmation: *5M*\n"
        f"📈 Trend: *{signal['trend_15m']}*\n\n"

        f"RSI: `{signal['rsi']:.1f}`\n"
        f"ATR: `{signal['atr']:.2f}`\n\n"

        "⚡ *FAST NORMAL SCALP*\n"
        "🛡 Anti-repeat ACTIVE\n"
        "⏰ Signal monitored\n\n"

        "⚠️ Signal only. "
        "Use appropriate risk."
    )


# ============================================================
# PENDING ORDER MESSAGE
# ============================================================

def format_pending(signal):

    if signal["direction"] == "BUY":

        emoji = "🟢"

        reason = (
            "Price must break resistance "
            "to activate the BUY."
        )

    else:

        emoji = "🔴"

        reason = (
            "Price must break support "
            "to activate the SELL."
        )

    expiry = datetime.fromtimestamp(
        signal["expires"],
        tz=timezone.utc
    ).strftime(
        "%H:%M UTC"
    )

    return (
        "👑 *KING GOLD SCALPER*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"{emoji} *{signal['type']} XAU/USD*\n\n"

        f"🚨 Entry / Trigger: "
        f"`{signal['entry']:.2f}`\n"

        f"🛑 Stop Loss: "
        f"`{signal['stop_loss']:.2f}`\n"

        f"🎯 TP1: "
        f"`{signal['tp1']:.2f}`\n"

        f"🎯 TP2: "
        f"`{signal['tp2']:.2f}`\n\n"

        f"📊 Confidence: "
        f"*{signal['confidence']:.0f}%*\n"

        f"📈 5M Trend: "
        f"*{signal['trend_5m']}*\n"

        f"📈 15M Trend: "
        f"*{signal['trend_15m']}*\n\n"

        f"💡 {reason}\n\n"

        f"⏰ Expires: `{expiry}`\n"
        "🟡 STATUS: *WAITING*\n\n"

        "⚠️ Signal only — "
        "place pending order manually in MT5."
    )


# ============================================================
# BREAKOUT MESSAGE
# ============================================================

def format_breakout(signal):

    return (
        "👑 *KING GOLD SCALPER*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "💥 *BREAKOUT RADAR*\n\n"

        f"💰 Current: "
        f"`{signal['price']:.2f}`\n\n"

        f"🔵 Resistance: "
        f"`{signal['resistance']:.2f}`\n"

        f"🔵 Support: "
        f"`{signal['support']:.2f}`\n\n"

        f"🟢 BUY STOP: "
        f"`{signal['buy_stop']:.2f}`\n"

        f"🔴 SELL STOP: "
        f"`{signal['sell_stop']:.2f}`\n\n"

        f"🧠 Bias: *{signal['bias']}*\n"
        f"📊 5M: *{signal['trend_5m']}*\n"
        f"📈 15M: *{signal['trend_15m']}*\n"
        f"⚡ ATR: `{signal['atr']:.2f}`\n\n"

        "🟡 STATUS: *WAITING FOR BREAKOUT*\n\n"

        "⚠️ Signal only. "
        "Confirm breakout before entry."
    )


# ============================================================
# SLINGSHOT MESSAGE
# ============================================================

def format_slingshot(signal):

    if signal["direction"] == "BUY":

        emoji = "🟢"

    else:

        emoji = "🔴"

    return (
        "👑 *KING GOLD SCALPER*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"🏹 *SLINGSHOT "
        f"{signal['direction']}*\n\n"

        f"{emoji} Entry: "
        f"`{signal['entry']:.2f}`\n"

        f"🛑 SL: "
        f"`{signal['stop_loss']:.2f}`\n"

        f"🎯 TP1: "
        f"`{signal['tp1']:.2f}`\n"

        f"🎯 TP2: "
        f"`{signal['tp2']:.2f}`\n\n"

        "💧 Liquidity: "
        f"`{signal['liquidity']}`\n"

        "🔄 Rejection: "
        f"`{signal['rejection']}`\n"

        "⚡ Momentum: "
        f"`{signal['momentum']}`\n\n"

        f"📊 Confidence: "
        f"*{signal['confidence']:.0f}%*\n"

        f"📈 5M: "
        f"*{signal['trend_5m']}*\n"

        f"📈 15M: "
        f"*{signal['trend_15m']}*\n\n"

        "🏹 *LIQUIDITY SWEEP REVERSAL*\n"
        "⚠️ Signal only."
    )


# ============================================================
# MARKET MOOD MESSAGE
# ============================================================

def format_mood(mood):

    return (
        "👑 *KING GOLD SCALPER*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🧠 *GOLD MARKET MOOD*\n\n"

        f"Market: *{mood['mood']}*\n\n"

        f"📉 1M: `{mood['1m']}`\n"
        f"📊 5M: `{mood['5m']}`\n"
        f"📈 15M: `{mood['15m']}`\n\n"

        f"RSI: `{mood['rsi']:.1f}`\n"
        f"ATR: `{mood['atr']:.2f}`\n"

        f"Volatility: *{mood['volatility']}*\n\n"

        "👑 KING GOLD SCALPER"
    )


# ============================================================
# LIVE SIGNAL MESSAGE
# ============================================================

def format_live_signal():

    cleanup_active_signals()

    if not active_signals:

        return (
            "👑 *KING GOLD SCALPER*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📡 *LIVE SIGNAL*\n\n"
            "🟡 No active signal."
        )

    signal = active_signals[-1]

    remaining = max(
        0,
        int(
            signal["expires"]
            - time.time()
        )
    )

    minutes = (
        remaining // 60
    )

    seconds = (
        remaining % 60
    )

    signal_type = signal.get(
        "type",
        "SIGNAL"
    )

    direction = signal.get(
        "direction",
        ""
    )

    return (
        "👑 *KING GOLD SCALPER*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"📡 *LIVE {signal_type}*\n\n"

        f"Direction: *{direction}*\n"

        f"Entry: `{signal.get('entry', 0):.2f}`\n"

        f"SL: `{signal.get('stop_loss', 0):.2f}`\n"

        f"TP1: `{signal.get('tp1', 0):.2f}`\n"

        f"TP2: `{signal.get('tp2', 0):.2f}`\n\n"

        f"⏰ Time remaining: "
        f"`{minutes:02d}:{seconds:02d}`\n"

        "🟢 STATUS: ACTIVE"
    )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = (
        update.effective_chat.id
    )

    subscribers.add(
        chat_id
    )

    await update.message.reply_text(
        welcome_message(),
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# ============================================================
# STOP
# ============================================================

async def stop(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = (
        update.effective_chat.id
    )

    subscribers.discard(
        chat_id
    )

    await update.message.reply_text(
        "⛔ *KING GOLD SCALPER*\n\n"
        "Automatic alerts stopped.\n\n"
        "Use /start to enable them again.",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# ============================================================
# STATUS
# ============================================================

async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    with state_lock:

        price = (
            f"{last_price:.2f}"
            if last_price
            else "Unavailable"
        )

        scan = (
            last_scan_time.strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
            if last_scan_time
            else "Not scanned"
        )

    last_type = (
        last_auto_signal["type"]
        or "NONE"
    )

    await update.message.reply_text(

        "👑 *KING GOLD SCALPER*\n"
        "━━━━━━━━━━━━━━━━━━\n"

        "🟢 Bot: RUNNING\n"
        "🟢 Scanner: ACTIVE\n"
        "🟡 Market: XAU/USD\n\n"

        f"💰 Price: `{price}`\n"
        f"👥 Subscribers: "
        f"`{len(subscribers)}`\n"

        f"⏱ Last scan: `{scan}`\n"

        f"📡 Last signal: "
        f"`{last_type}`\n\n"

        "🛡 Anti-repeat: ACTIVE\n"
        "🏹 Slingshot: READY\n"
        "💥 Breakout Radar: READY\n"
        "🟢 BUY STOP: READY\n"
        "🔴 SELL STOP: READY\n\n"

        "⚡ SIGNAL-ONLY MODE",

        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# ============================================================
# MANUAL SCAN
# ============================================================

async def scan(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    subscribers.add(
        update.effective_chat.id
    )

    message = await update.message.reply_text(
        "🔎 Scanning XAU/USD..."
    )

    signal = generate_scalp_signal()

    if signal:

        await message.edit_text(
            format_scalp(signal),
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    else:

        await message.edit_text(
            "🟡 *KING GOLD SCALPER*\n\n"
            "No clean scalp setup right now.",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )


# ============================================================
# BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = (
        update.callback_query
    )

    await query.answer()

    chat_id = (
        query.message.chat_id
    )

    action = query.data

    subscribers.add(
        chat_id
    )

    # ========================================================
    # SCALP BUY
    # ========================================================

    if action == "buy":

        await query.message.reply_text(
            "🟢 Scanning BUY setup..."
        )

        signal = (
            generate_scalp_signal()
        )

        if (
            signal
            and
            signal["direction"]
            == "BUY"
        ):

            await query.message.reply_text(
                format_scalp(signal),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )

        else:

            await query.message.reply_text(
                "🟡 No BUY setup right now.",
                reply_markup=main_menu()
            )

    # ========================================================
    # SCALP SELL
    # ========================================================

    elif action == "sell":

        await query.message.reply_text(
            "🔴 Scanning SELL setup..."
        )

        signal = (
            generate_scalp_signal()
        )

        if (
            signal
            and
            signal["direction"]
            == "SELL"
        ):

            await query.message.reply_text(
                format_scalp(signal),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )

        else:

            await query.message.reply_text(
                "🟡 No SELL setup right now.",
                reply_markup=main_menu()
            )

    # ========================================================
    # BUY STOP
    # ========================================================

    elif action == "buystop":

        await query.message.reply_text(
            "🟢 Calculating BUY STOP..."
        )

        signal = (
            generate_pending_signal(
                "BUY"
            )
        )

        if signal:

            add_active_signal(
                signal
            )

            await query.message.reply_text(
                format_pending(signal),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )

        else:

            await query.message.reply_text(
                "🟡 Unable to calculate BUY STOP.",
                reply_markup=main_menu()
            )

    # ========================================================
    # SELL STOP
    # ========================================================

    elif action == "sellstop":

        await query.message.reply_text(
            "🔴 Calculating SELL STOP..."
        )

        signal = (
            generate_pending_signal(
                "SELL"
            )
        )

        if signal:

            add_active_signal(
                signal
            )

            await query.message.reply_text(
                format_pending(signal),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )

        else:

            await query.message.reply_text(
                "🟡 Unable to calculate SELL STOP.",
                reply_markup=main_menu()
            )

    # ========================================================
    # SLINGSHOT
    # ========================================================

    elif action == "slingshot":

        await query.message.reply_text(
            "🏹 Searching for liquidity sweep..."
        )

        signal = (
            generate_slingshot()
        )

        if signal:

            add_active_signal(
                signal
            )

            await query.message.reply_text(
                format_slingshot(signal),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )

        else:

            await query.message.reply_text(
                "🟡 No Slingshot setup detected.\n\n"
                "Waiting for liquidity sweep + rejection + momentum.",
                reply_markup=main_menu()
            )

    # ========================================================
    # BREAKOUT
    # ========================================================

    elif action == "breakout":

        await query.message.reply_text(
            "💥 Running Breakout Radar..."
        )

        signal = (
            generate_breakout_signal()
        )

        if signal:

            await query.message.reply_text(
                format_breakout(signal),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )

        else:

            await query.message.reply_text(
                "🟡 Breakout Radar unavailable.",
                reply_markup=main_menu()
            )

    # ========================================================
    # AUTO
    # ========================================================

    elif action == "auto":

        await query.message.reply_text(
            "⚡ *AUTO SCALPING ENABLED*\n\n"
            "👑 KING GOLD SCALPER will scan XAU/USD automatically.\n\n"
            "🛡 Duplicate protection: ACTIVE\n"
            "⏰ Signal expiry: ACTIVE",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    # ========================================================
    # SCAN
    # ========================================================

    elif action == "scan":

        await query.message.reply_text(
            "🔎 Scanning XAU/USD..."
        )

        signal = (
            generate_scalp_signal()
        )

        if signal:

            await query.message.reply_text(
                format_scalp(signal),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )

        else:

            await query.message.reply_text(
                "🟡 No qualifying scalp setup.",
                reply_markup=main_menu()
            )

    # ========================================================
    # MARKET MOOD
    # ========================================================

    elif action == "mood":

        await query.message.reply_text(
            "🧠 Reading Gold market mood..."
        )

        mood = (
            generate_market_mood()
        )

        if mood:

            await query.message.reply_text(
                format_mood(mood),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )

        else:

            await query.message.reply_text(
                "🟡 Market mood unavailable.",
                reply_markup=main_menu()
            )

    # ========================================================
    # LIVE SIGNAL
    # ========================================================

    elif action == "live":

        await query.message.reply_text(
            format_live_signal(),
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    # ========================================================
    # STATUS
    # ========================================================

    elif action == "status":

        with state_lock:

            price = (
                f"{last_price:.2f}"
                if last_price
                else "Unavailable"
            )

        await query.message.reply_text(
            "👑 *KING GOLD SCALPER*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🟢 Bot: RUNNING\n"
            "🟢 Scanner: ACTIVE\n"
            "🟡 XAU/USD: CONNECTED\n"
            f"💰 Price: `{price}`\n"
            f"👥 Subscribers: `{len(subscribers)}`\n"
            "🛡 Anti-repeat: ACTIVE\n"
            "💥 Breakout Radar: READY\n"
            "🏹 Slingshot: READY",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    # ========================================================
    # STOP
    # ========================================================

    elif action == "stop":

        subscribers.discard(
            chat_id
        )

        await query.message.reply_text(
            "⛔ *AUTO ALERTS STOPPED*\n\n"
            "You can still use manual scans.",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )


# ============================================================
# AUTOMATIC SCANNER
# ============================================================

async def automatic_scanner(
    application
):

    logger.info(
        "👑 KING GOLD SCALPER scanner started."
    )

    while True:

        try:

            if not subscribers:

                await asyncio.sleep(
                    SCAN_SECONDS
                )

                continue

            logger.info(
                "Scanning XAU/USD..."
            )

            signal = (
                generate_scalp_signal()
            )

            if signal:

                if should_send_signal(
                    signal
                ):

                    message = (
                        format_scalp(
                            signal
                        )
                    )

                    logger.info(
                        "NEW AUTO SIGNAL: %s %.2f",
                        signal["direction"],
                        signal["entry"]
                    )

                    failed = []

                    for chat_id in list(
                        subscribers
                    ):

                        try:

                            await application.bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode="Markdown",
                                reply_markup=main_menu()
                            )

                        except Exception as e:

                            logger.error(
                                "Telegram error %s: %s",
                                chat_id,
                                e
                            )

                            failed.append(
                                chat_id
                            )

                    for chat_id in failed:

                        subscribers.discard(
                            chat_id
                        )

                    remember_signal(
                        signal
                    )

                    add_active_signal(
                        signal
                    )

                else:

                    logger.info(
                        "Duplicate scalp signal blocked."
                    )

            else:

                logger.info(
                    "No scalp signal."
                )

        except Exception as e:

            logger.exception(
                "Automatic scanner error: %s",
                e
            )

        await asyncio.sleep(
            SCAN_SECONDS
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Telegram error: %s",
        context.error
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN environment variable is missing."
        )

    if not TWELVE_API_KEY:

        raise RuntimeError(
            "TWELVE_DATA_API_KEY environment variable is missing."
        )

    # ========================================================
    # HEALTH SERVER
    # ========================================================

    web_thread = threading.Thread(
        target=run_web_server,
        daemon=True
    )

    web_thread.start()

    logger.info(
        "Health server started on port %s",
        PORT
    )

    # ========================================================
    # TELEGRAM APPLICATION
    # ========================================================

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # ========================================================
    # STARTUP HOOK
    # ========================================================

    async def post_init(
        app_instance
    ):

        asyncio.create_task(
            automatic_scanner(
                app_instance
            )
        )

        logger.info(
            "Automatic scanner task created."
        )

    application.post_init = (
        post_init
    )

    # ========================================================
    # COMMANDS
    # ========================================================

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "stop",
            stop
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status
        )
    )

    application.add_handler(
        CommandHandler(
            "scan",
            scan
        )
    )

    # ========================================================
    # BUTTONS
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_error_handler(
        error_handler
    )

    # ========================================================
    # STARTUP LOG
    # ========================================================

    logger.info(
        "======================================"
    )

    logger.info(
        "👑 KING GOLD SCALPER"
    )

    logger.info(
        "🟡 XAU/USD"
    )

    logger.info(
        "⚡ NORMAL SCALPING"
    )

    logger.info(
        "🟢 BUY STOP"
    )

    logger.info(
        "🔴 SELL STOP"
    )

    logger.info(
        "💥 BREAKOUT RADAR"
    )

    logger.info(
        "🏹 SLINGSHOT"
    )

    logger.info(
        "🧠 MARKET MOOD"
    )

    logger.info(
        "🛡 ANTI-REPEAT ACTIVE"
    )

    logger.info(
        "======================================"
    )

    # ========================================================
    # RUN
    # ========================================================

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
