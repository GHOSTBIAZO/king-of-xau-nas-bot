import os
import time
import threading
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ============================================================
# KING GOLD SCALPER — TELEGRAM BOT
# XAU/USD FAST NORMAL SCALPING
# ============================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TWELVE_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

PORT = int(os.getenv("PORT", "10000"))

SYMBOL = "XAU/USD"

# Scan frequency
SCAN_SECONDS = 60

# Twelve Data settings
OUTPUT_SIZE = 100

# Signal settings
EMA_FAST = 9
EMA_MID = 21
EMA_SLOW = 50

RSI_PERIOD = 14
ATR_PERIOD = 14

# Minimum confidence — deliberately NOT strict
MIN_CONFIDENCE = 60

# Signal cooldown
SIGNAL_COOLDOWN = 180

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)

logger = logging.getLogger("KING_GOLD_SCALPER")

# ============================================================
# FLASK HEALTH SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return jsonify({
        "bot": "KING GOLD SCALPER",
        "status": "running",
        "symbol": SYMBOL,
        "timeframe": "1M / 5M / 15M",
        "server_time": datetime.now(timezone.utc).isoformat()
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "OK",
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

last_signal_key = None
last_signal_time = 0

last_scan_time = None
last_price = None

scanner_running = True

state_lock = threading.Lock()


# ============================================================
# TELEGRAM MESSAGE HELPERS
# ============================================================

def main_menu():

    keyboard = [
        [
            InlineKeyboardButton("🟢 SCALP BUY", callback_data="buy"),
            InlineKeyboardButton("🔴 SCALP SELL", callback_data="sell"),
        ],
        [
            InlineKeyboardButton("⚡ AUTO SCALPING", callback_data="auto"),
        ],
        [
            InlineKeyboardButton("📊 SCAN NOW", callback_data="scan"),
            InlineKeyboardButton("❤️ STATUS", callback_data="status"),
        ],
        [
            InlineKeyboardButton("⛔ STOP ALERTS", callback_data="stop"),
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def welcome_message():

    return (
        "👑 *KING GOLD SCALPER*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🟡 *XAU/USD FAST SCALPING*\n\n"
        "⚡ Normal scalping mode\n"
        "📉 1M entry\n"
        "📊 5M confirmation\n"
        "📈 15M trend\n\n"
        "Indicators:\n"
        "• EMA 9 / 21 / 50\n"
        "• RSI 14\n"
        "• ATR 14\n"
        "• Momentum\n\n"
        "🎯 Automatic Entry / SL / TP\n"
        "🔄 Automatic scanning\n\n"
        "Select an option below:"
    )


# ============================================================
# TWELVE DATA
# ============================================================

def get_candles(interval):

    if not TWELVE_API_KEY:
        logger.error("TWELVE_DATA_API_KEY is missing.")
        return []

    url = "https://api.twelvedata.com/time_series"

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
                "Twelve Data HTTP error: %s",
                response.status_code
            )
            return []

        data = response.json()

        if "values" not in data:

            logger.error(
                "Twelve Data error: %s",
                data.get("message", data)
            )

            return []

        candles = []

        for row in reversed(data["values"]):

            try:
                candles.append({
                    "datetime": row["datetime"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
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
# INDICATORS
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (
            (price - result) * multiplier
        ) + result

    return result


def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1)) +
            gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) +
            losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        )

        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    value = sum(true_ranges[:period]) / period

    for tr in true_ranges[period:]:
        value = (
            (value * (period - 1)) + tr
        ) / period

    return value


# ============================================================
# ANALYSIS
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

    ema9 = ema(closes, EMA_FAST)
    ema21 = ema(closes, EMA_MID)
    ema50 = ema(closes, EMA_SLOW)

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

    score_buy = 0
    score_sell = 0

    # EMA direction
    if ema9 > ema21:
        score_buy += 2
    elif ema9 < ema21:
        score_sell += 2

    # Price vs EMA50
    if price > ema50:
        score_buy += 2
    elif price < ema50:
        score_sell += 2

    # Candle direction
    if current["close"] > current["open"]:
        score_buy += 1
    elif current["close"] < current["open"]:
        score_sell += 1

    # Momentum
    if current["close"] > previous["close"]:
        score_buy += 1
    elif current["close"] < previous["close"]:
        score_sell += 1

    # RSI
    if 52 <= rsi_value <= 70:
        score_buy += 2

    if 30 <= rsi_value <= 48:
        score_sell += 2

    # Avoid extreme RSI entries
    if rsi_value > 75:
        score_buy -= 1

    if rsi_value < 25:
        score_sell -= 1

    if score_buy > score_sell:
        direction = "BUY"
        score = score_buy
    elif score_sell > score_buy:
        direction = "SELL"
        score = score_sell
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
        "atr": atr_value
    }


# ============================================================
# SIGNAL ENGINE
# ============================================================

def generate_signal():

    global last_price
    global last_scan_time

    candles_1m = get_candles("1min")

    if not candles_1m:
        return None

    candles_5m = get_candles("5min")

    if not candles_5m:
        return None

    candles_15m = get_candles("15min")

    if not candles_15m:
        return None

    analysis_1m = analyze_timeframe(candles_1m)
    analysis_5m = analyze_timeframe(candles_5m)
    analysis_15m = analyze_timeframe(candles_15m)

    if not analysis_1m:
        return None

    if not analysis_5m:
        return None

    if not analysis_15m:
        return None

    price = analysis_1m["price"]

    last_price = price
    last_scan_time = datetime.now(timezone.utc)

    # ========================================================
    # NORMAL SCALPING LOGIC
    # ========================================================

    buy_points = 0
    sell_points = 0

    # 1M is the entry direction
    if analysis_1m["direction"] == "BUY":
        buy_points += 4

    elif analysis_1m["direction"] == "SELL":
        sell_points += 4

    # 5M confirmation
    if analysis_5m["direction"] == "BUY":
        buy_points += 3

    elif analysis_5m["direction"] == "SELL":
        sell_points += 3

    # 15M trend
    if analysis_15m["direction"] == "BUY":
        buy_points += 2

    elif analysis_15m["direction"] == "SELL":
        sell_points += 2

    # ========================================================
    # ALLOW NORMAL SCALPS EVEN WHEN HIGHER TIMEFRAME
    # IS NOT PERFECTLY ALIGNED
    # ========================================================

    if buy_points > sell_points and buy_points >= 5:

        direction = "BUY"

        confidence = min(
            95,
            55 + (buy_points * 4)
        )

    elif sell_points > buy_points and sell_points >= 5:

        direction = "SELL"

        confidence = min(
            95,
            55 + (sell_points * 4)
        )

    else:

        return None

    # ========================================================
    # SL / TP
    # ========================================================

    atr_value = analysis_1m["atr"]

    if atr_value <= 0:
        return None

    # Gold scalping multiplier
    sl_distance = atr_value * 1.4

    tp1_distance = atr_value * 1.5
    tp2_distance = atr_value * 2.3

    if direction == "BUY":

        entry = price
        stop_loss = entry - sl_distance
        tp1 = entry + tp1_distance
        tp2 = entry + tp2_distance

    else:

        entry = price
        stop_loss = entry + sl_distance
        tp1 = entry - tp1_distance
        tp2 = entry - tp2_distance

    return {
        "symbol": SYMBOL,
        "direction": direction,
        "confidence": confidence,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "atr": atr_value,
        "rsi": analysis_1m["rsi"],
        "ema9": analysis_1m["ema9"],
        "ema21": analysis_1m["ema21"],
        "ema50": analysis_1m["ema50"],
        "trend_5m": analysis_5m["direction"],
        "trend_15m": analysis_15m["direction"],
    }


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def format_signal(signal):

    direction = signal["direction"]

    if direction == "BUY":
        emoji = "🟢"
        action = "BUY"
    else:
        emoji = "🔴"
        action = "SELL"

    return (
        "👑 *KING GOLD SCALPER*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"{emoji} *SCALP {action} XAU/USD*\n\n"

        f"💰 Entry: `{signal['entry']:.2f}`\n"
        f"🛑 Stop Loss: `{signal['stop_loss']:.2f}`\n"
        f"🎯 TP1: `{signal['tp1']:.2f}`\n"
        f"🎯 TP2: `{signal['tp2']:.2f}`\n\n"

        f"📊 Confidence: *{signal['confidence']:.0f}%*\n"
        f"⏱ Entry TF: *1M*\n"
        f"📊 Confirmation: *5M*\n"
        f"📈 HTF Trend: *{signal['trend_15m']}*\n\n"

        f"RSI: `{signal['rsi']:.1f}`\n"
        f"EMA 9: `{signal['ema9']:.2f}`\n"
        f"EMA 21: `{signal['ema21']:.2f}`\n"
        f"EMA 50: `{signal['ema50']:.2f}`\n"
        f"ATR: `{signal['atr']:.2f}`\n\n"

        "⚡ *FAST NORMAL SCALP*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Trade with appropriate risk."
    )


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    subscribers.add(chat_id)

    await update.message.reply_text(
        welcome_message(),
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    subscribers.discard(chat_id)

    await update.message.reply_text(
        "⛔ *Gold scalp alerts stopped.*\n\n"
        "Use /start whenever you want to receive them again.",
        parse_mode="Markdown"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    with state_lock:

        scan = (
            last_scan_time.strftime("%Y-%m-%d %H:%M:%S UTC")
            if last_scan_time
            else "Not scanned yet"
        )

        price = (
            f"{last_price:.2f}"
            if last_price
            else "Unavailable"
        )

    await update.message.reply_text(
        "❤️ *KING GOLD SCALPER — STATUS*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🟢 Bot: RUNNING\n"
        "🟢 Scanner: ACTIVE\n"
        "🟡 Market: XAU/USD\n"
        f"💰 Price: `{price}`\n"
        f"👥 Subscribers: `{len(subscribers)}`\n"
        f"⏱ Last scan: `{scan}`\n"
        "⚡ Mode: NORMAL SCALPING",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = await update.message.reply_text(
        "🔎 Scanning XAU/USD..."
    )

    signal = generate_signal()

    if signal:

        await message.edit_text(
            format_signal(signal),
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    else:

        await message.edit_text(
            "🟡 *XAU/USD SCAN*\n\n"
            "No clean scalp direction right now.\n"
            "The scanner will continue automatically.",
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

    query = update.callback_query

    await query.answer()

    chat_id = query.message.chat_id

    action = query.data

    if action == "buy":

        subscribers.add(chat_id)

        await query.message.reply_text(
            "🟢 *Manual BUY scan requested.*\n\n"
            "Scanning Gold...",
            parse_mode="Markdown"
        )

        signal = generate_signal()

        if signal and signal["direction"] == "BUY":

            await query.message.reply_text(
                format_signal(signal),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )

        else:

            await query.message.reply_text(
                "🟡 No BUY setup detected right now.",
                reply_markup=main_menu()
            )

    elif action == "sell":

        subscribers.add(chat_id)

        await query.message.reply_text(
            "🔴 *Manual SELL scan requested.*\n\n"
            "Scanning Gold...",
            parse_mode="Markdown"
        )

        signal = generate_signal()

        if signal and signal["direction"] == "SELL":

            await query.message.reply_text(
                format_signal(signal),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )

        else:

            await query.message.reply_text(
                "🟡 No SELL setup detected right now.",
                reply_markup=main_menu()
            )

    elif action == "scan":

        subscribers.add(chat_id)

        await query.message.reply_text(
            "🔎 Scanning XAU/USD..."
        )

        signal = generate_signal()

        if signal:

            await query.message.reply_text(
                format_signal(signal),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )

        else:

            await query.message.reply_text(
                "🟡 No qualifying scalp direction right now.",
                reply_markup=main_menu()
            )

    elif action == "auto":

        subscribers.add(chat_id)

        await query.message.reply_text(
            "⚡ *AUTO SCALPING ENABLED*\n\n"
            "You will receive automatic XAU/USD scalp signals.",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    elif action == "stop":

        subscribers.discard(chat_id)

        await query.message.reply_text(
            "⛔ *AUTO ALERTS STOPPED*",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    elif action == "status":

        with state_lock:

            scan_time = (
                last_scan_time.strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                )
                if last_scan_time
                else "Not scanned"
            )

            price = (
                f"{last_price:.2f}"
                if last_price
                else "Unavailable"
            )

        await query.message.reply_text(
            "❤️ *KING GOLD SCALPER*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🟢 Bot: RUNNING\n"
            "🟢 Scanner: ACTIVE\n"
            "🟡 XAU/USD: CONNECTED\n"
            f"💰 Price: `{price}`\n"
            f"👥 Subscribers: `{len(subscribers)}`\n"
            f"⏱ Last scan: `{scan_time}`",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )


# ============================================================
# AUTOMATIC SCANNER
# ============================================================

async def automatic_scanner(application):

    global last_signal_key
    global last_signal_time

    logger.info("Automatic Gold scanner started.")

    while True:

        try:

            if not subscribers:

                await __import__("asyncio").sleep(
                    SCAN_SECONDS
                )

                continue

            logger.info(
                "Scanning XAU/USD..."
            )

            signal = generate_signal()

            if signal:

                direction = signal["direction"]

                # Round price to avoid duplicate spam
                price_key = round(
                    signal["entry"],
                    1
                )

                signal_key = (
                    direction,
                    price_key
                )

                current_time = time.time()

                cooldown_ok = (
                    current_time -
                    last_signal_time
                    >= SIGNAL_COOLDOWN
                )

                new_signal = (
                    signal_key != last_signal_key
                )

                if cooldown_ok and new_signal:

                    message = format_signal(
                        signal
                    )

                    logger.info(
                        "NEW SIGNAL: %s %.2f",
                        direction,
                        signal["entry"]
                    )

                    failed_chats = []

                    for chat_id in list(subscribers):

                        try:

                            await application.bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode="Markdown",
                                reply_markup=main_menu()
                            )

                        except Exception as e:

                            logger.error(
                                "Telegram send error for %s: %s",
                                chat_id,
                                e
                            )

                            failed_chats.append(chat_id)

                    for chat_id in failed_chats:
                        subscribers.discard(chat_id)

                    last_signal_key = signal_key
                    last_signal_time = current_time

            else:

                logger.info(
                    "No scalp signal."
                )

        except Exception as e:

            logger.exception(
                "Scanner error: %s",
                e
            )

        await __import__("asyncio").sleep(
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

    # Render health server
    web_thread = threading.Thread(
        target=run_web_server,
        daemon=True
    )

    web_thread.start()

    logger.info(
        "Health server started on port %s",
        PORT
    )

    # Telegram application
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
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

    # Buttons
    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "===================================="
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
        "📊 1M / 5M / 15M"
    )

    logger.info(
        "===================================="
    )

    # Run polling
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
