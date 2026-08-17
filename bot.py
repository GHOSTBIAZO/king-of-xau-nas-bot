import os
import logging
from threading import Thread

import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================
# SETTINGS
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
PORT = int(os.getenv("PORT", "10000"))

XAU_SYMBOL = "XAU/USD"

INTERVAL = "15min"
OUTPUT_SIZE = 100

# =========================
# LOGGING
# =========================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# =========================
# WEB SERVER
# =========================

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "King of XAU_NAS Gold Bot is running!"


@web_app.route("/health")
def health():
    return "OK"


def run_web_server():
    web_app.run(
        host="0.0.0.0",
        port=PORT
    )


# =========================
# TWELVE DATA API
# =========================

def twelve_data_request(endpoint, params):

    if not TWELVE_DATA_API_KEY:
        return None, "Twelve Data API key is missing."

    params["apikey"] = TWELVE_DATA_API_KEY

    url = f"https://api.twelvedata.com/{endpoint}"

    try:
        response = requests.get(
            url,
            params=params,
            timeout=15
        )

        data = response.json()

        if data.get("status") == "error":
            return None, data.get(
                "message",
                "Twelve Data returned an error."
            )

        return data, None

    except Exception as error:

        logger.error(
            "API error: %s",
            error
        )

        return None, "Unable to connect to Twelve Data."


# =========================
# LIVE PRICE
# =========================

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


# =========================
# GET GOLD CANDLES
# =========================

def get_candles():

    data, error = twelve_data_request(
        "time_series",
        {
            "symbol": XAU_SYMBOL,
            "interval": INTERVAL,
            "outputsize": OUTPUT_SIZE,
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
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
            })

        return candles, None

    except Exception as error:

        logger.error(
            "Candle error: %s",
            error
        )

        return None, "Unable to process candle data."


# =========================
# EMA
# =========================

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


# =========================
# RSI
# =========================

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

    average_gain = sum(
        gains[:period]
    ) / period

    average_loss = sum(
        losses[:period]
    ) / period

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


# =========================
# ATR
# =========================

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

    atr = sum(
        true_ranges[:period]
    ) / period

    for value in true_ranges[period:]:

        atr = (
            (atr * (period - 1)) + value
        ) / period

    return atr


# =========================
# GOLD ANALYSIS
# =========================

def analyze_gold():

    candles, error = get_candles()

    if error:
        return None, error

    if len(candles) < 50:
        return None, "Not enough candle data."

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

    if None in [ema20, ema50, rsi, atr]:
        return None, "Unable
