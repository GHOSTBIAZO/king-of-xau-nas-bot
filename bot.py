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
        return None, "Unable to calculate technical indicators."

    # =========================
    # SIGNAL SCORE
    # =========================

    score = 0

    if price > ema20:
        score += 1
    else:
        score -= 1

    if ema20 > ema50:
        score += 2
    else:
        score -= 2

    if 50 <= rsi <= 70:
        score += 1
    elif 30 <= rsi < 50:
        score -= 1
    elif rsi > 70:
        score -= 1
    elif rsi < 30:
        score += 1

    # =========================
    # SIGNAL
    # =========================

    if score >= 3:
        signal = "BUY"
        icon = "🟢"
    elif score <= -3:
        signal = "SELL"
        icon = "🔴"
    else:
        signal = "WAIT"
        icon = "🟡"

    # =========================
    # TREND
    # =========================

    if price > ema20 and ema20 > ema50:
        trend = "BULLISH 📈"
    elif price < ema20 and ema20 < ema50:
        trend = "BEARISH 📉"
    else:
        trend = "MIXED ↔️"

    # =========================
    # ENTRY / SL / TP
    # =========================

    entry = price

    if signal == "BUY":
        stop_loss = entry - (atr * 1.5)
        tp1 = entry + (atr * 1.5)
        tp2 = entry + (atr * 3)

    elif signal == "SELL":
        stop_loss = entry + (atr * 1.5)
        tp1 = entry - (atr * 1.5)
        tp2 = entry - (atr * 3)

    else:
        stop_loss = None
        tp1 = None
        tp2 = None

    confidence = min(
        95,
        max(50, 50 + abs(score) * 10)
    )

    return {
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "signal": signal,
        "icon": icon,
        "trend": trend,
        "confidence": confidence,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
    }, None


# =========================
# FORMAT ANALYSIS
# =========================

def format_analysis(result):

    message = (
        "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"
        "🟡 *XAU/USD*\n\n"
        f"💰 Price: `${result['price']:,.2f}`\n"
        f"📈 Trend: *{result['trend']}*\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 *TECHNICAL ANALYSIS*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"EMA 20: `{result['ema20']:,.2f}`\n"
        f"EMA 50: `{result['ema50']:,.2f}`\n"
        f"RSI 14: `{result['rsi']:.1f}`\n"
        f"ATR 14: `{result['atr']:.2f}`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 *SIGNAL*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{result['icon']} Signal: *{result['signal']}*\n"
        f"💪 Confidence: *{result['confidence']}%*\n"
    )

    if result["signal"] != "WAIT":
        message += (
            "\n"
            f"🎯 Entry: `${result['entry']:,.2f}`\n"
            f"🛑 Stop Loss: `${result['stop_loss']:,.2f}`\n"
            f"🎯 Take Profit 1: `${result['tp1']:,.2f}`\n"
            f"🎯 Take Profit 2: `${result['tp2']:,.2f}`\n"
        )
    else:
        message += (
            "\n"
            "⏳ No strong setup right now.\n"
            "Wait for confirmation.\n"
        )

    message += (
        "\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ Timeframe: *{INTERVAL}*\n"
        "📡 Data: Twelve Data\n\n"
        "⚠️ Analysis only — not financial advice.\n"
        "⚠️ No signal guarantees profit."
    )

    return message


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton(
                "🟡 GOLD ANALYSIS",
                callback_data="gold"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 GOLD STATUS",
                callback_data="status"
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
        "👑 *KING OF XAU_NAS* 👑\n\n"
        "Welcome to your Gold trading assistant.\n\n"
        "🟡 *XAU/USD — GOLD*\n\n"
        "📡 Live price\n"
        "📈 Technical analysis\n"
        "🎯 Entry / SL / TP\n"
        "💪 Signal confidence\n\n"
        "Choose an option:"
    )

    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# =========================
# GOLD COMMAND
# =========================

async def gold_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🔎 Analyzing XAU/USD...\nPlease wait..."
    )

    result, error = analyze_gold()

    if error:
        await update.message.reply_text(
            f"❌ *GOLD ANALYSIS ERROR*\n\n{error}",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        format_analysis(result),
        parse_mode="Markdown"
    )


# =========================
# STATUS
# =========================

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    price, error = get_price()

    if price is not None:
        price_text = f"${price:,.2f}"
        data_status = "🟢 ONLINE"
    else:
        price_text = "Unavailable"
        data_status = "🔴 OFFLINE"

    message = (
        "👑 *KING OF XAU_NAS STATUS*\n\n"
        "🟢 Telegram Bot: ONLINE\n"
        f"🟡 XAU/USD: {price_text}\n"
        f"📡 Twelve Data: {data_status}\n"
        "📊 Gold Scanner: READY\n\n"
        "🔵 Nasdaq: DISABLED"
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown"
    )


# =========================
# HELP
# =========================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = (
        "ℹ️ *KING OF XAU_NAS — GOLD*\n\n"
        "/start — Main menu\n"
        "/gold — Gold analysis\n"
        "/status — Bot status\n"
        "/help — Help\n\n"
        "📊 Indicators:\n"
        "• EMA 20\n"
        "• EMA 50\n"
        "• RSI 14\n"
        "• ATR 14\n\n"
        "🟢 BUY\n"
        "🔴 SELL\n"
        "🟡 WAIT\n\n"
        "⚠️ Trading involves risk."
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown"
    )


# =========================
# BUTTON HANDLER
# =========================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    if query.data == "gold":

        await query.edit_message_text(
            "🔎 *Analyzing XAU/USD...*\n\nPlease wait...",
            parse_mode="Markdown"
        )

        result, error = analyze_gold()

        if error:
            message = (
                "❌ *GOLD ANALYSIS ERROR*\n\n"
                f"{error}"
            )
        else:
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
                "📊 Gold Scanner: READY"
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

    elif query.data == "help":

        message = (
            "ℹ️ *KING OF XAU_NAS — GOLD*\n\n"
            "🟡 XAU/USD only\n\n"
            "✅ Live price\n"
            "✅ EMA analysis\n"
            "✅ RSI analysis\n"
            "✅ ATR analysis\n"
            "✅ BUY / SELL / WAIT\n"
            "✅ Entry\n"
            "✅ Stop Loss\n"
            "✅ Take Profit\n\n"
            "⚠️ Analysis only."
        )

        await query.edit_message_text(
            message,
            parse_mode="Markdown"
        )


# =========================
# MAIN
# =========================

def main():

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not TWELVE_DATA_API_KEY:
        raise RuntimeError(
            "TWELVE_DATA_API_KEY is missing."
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
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("status", status_command)
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    logger.info(
        "King of XAU_NAS Gold Bot started!"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
