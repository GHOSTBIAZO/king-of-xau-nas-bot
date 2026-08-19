import os
import json
import time
import asyncio
import logging
from threading import Thread, Lock
from datetime import datetime, timezone

import requests
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ============================================================
# 👑 KING OF XAU_NAS — GOLD
# AUTOMATIC TELEGRAM GOLD SCANNER
# ============================================================

BOT_NAME = "👑 KING OF XAU_NAS — GOLD"

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

PORT = int(os.getenv("PORT", "10000"))

# ============================================================
# GOLD SETTINGS
# ============================================================

XAU_SYMBOL = "XAU/USD"

INTERVAL = "15min"
OUTPUT_SIZE = 100

SCAN_INTERVAL_SECONDS = 600  # 10 minutes

# ============================================================
# FILES
# ============================================================

CHAT_ID_FILE = "telegram_chat_id.json"

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(BOT_NAME)

# ============================================================
# GLOBAL STATE
# ============================================================

telegram_application = None

chat_id_lock = Lock()

last_signal_key = None
last_signal_time = 0

scanner_running = False

# ============================================================
# FLASK SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return f"""
    <html>
        <head>
            <title>{BOT_NAME}</title>
        </head>
        <body style="background:#111;color:white;font-family:Arial;text-align:center;padding-top:50px;">
            <h1>{BOT_NAME}</h1>
            <h2>🟢 BOT ONLINE</h2>
            <p>Market: XAU/USD</p>
            <p>Timeframe: 15 Minutes</p>
            <p>Scanner: Automatic</p>
        </body>
    </html>
    """


@app.route("/health")
def health():
    return {
        "status": "online",
        "bot": BOT_NAME,
        "market": "XAU/USD",
        "timeframe": INTERVAL,
        "scanner": scanner_running,
    }


def run_flask():
    try:
        app.run(
            host="0.0.0.0",
            port=PORT,
            debug=False,
            use_reloader=False,
        )
    except Exception as e:
        logger.error(f"Flask error: {e}")


# ============================================================
# CHAT ID STORAGE
# ============================================================

def load_chat_id():
    """
    Loads the saved Telegram Chat ID.
    """

    try:
        if not os.path.exists(CHAT_ID_FILE):
            return None

        with open(CHAT_ID_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        chat_id = data.get("chat_id")

        if chat_id:
            return str(chat_id)

    except Exception as e:
        logger.error(f"Could not load Chat ID: {e}")

    return None


def save_chat_id(chat_id):
    """
    Saves the Telegram Chat ID locally.
    """

    try:
        with chat_id_lock:

            with open(
                CHAT_ID_FILE,
                "w",
                encoding="utf-8",
            ) as file:

                json.dump(
                    {
                        "chat_id": str(chat_id),
                        "saved_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    },
                    file,
                    indent=4,
                )

        logger.info(
            f"Telegram Chat ID saved automatically: {chat_id}"
        )

        return True

    except Exception as e:
        logger.error(f"Could not save Chat ID: {e}")
        return False


# ============================================================
# TELEGRAM SEND MESSAGE
# ============================================================

async def send_message(message):
    """
    Sends a Telegram message to the automatically
    detected Chat ID.
    """

    global telegram_application

    chat_id = load_chat_id()

    if not chat_id:
        logger.warning(
            "No TELEGRAM_CHAT_ID configured. "
            "Send /start to the bot first."
        )
        return False

    if telegram_application is None:
        logger.warning(
            "Telegram application is not ready."
        )
        return False

    try:

        await telegram_application.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown",
        )

        return True

    except Exception as e:

        logger.error(
            f"Telegram send error: {e}"
        )

        return False


# ============================================================
# /START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.effective_chat:
        return

    chat_id = update.effective_chat.id

    username = ""

    if update.effective_user:

        if update.effective_user.username:
            username = (
                f"@{update.effective_user.username}"
            )

    # Automatically save Chat ID
    saved = save_chat_id(chat_id)

    if saved:

        message = (
            "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"
            "🟢 *BOT CONNECTED*\n\n"
            f"👤 User: {username or 'Telegram User'}\n"
            f"🆔 Chat ID: `{chat_id}`\n\n"
            "✅ Your Telegram Chat ID has been "
            "automatically detected and saved.\n\n"
            "🟡 Market: XAU/USD\n"
            "⏱ Timeframe: 15 Minutes\n"
            "🤖 Automatic Scanner: ON\n\n"
            "Use /scan to request a live GOLD scan.\n"
            "Use /status to check the bot."
        )

    else:

        message = (
            "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"
            "⚠️ I detected your Chat ID but could "
            "not save it.\n\n"
            f"🆔 Chat ID: `{chat_id}`"
        )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
    )


# ============================================================
# /STATUS
# ============================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = load_chat_id()

    if chat_id:
        chat_status = "🟢 CONNECTED"
    else:
        chat_status = "🔴 NOT CONNECTED"

    message = (
        "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 *BOT STATUS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Telegram: {chat_status}\n"
        f"Market: 🟡 XAU/USD\n"
        f"Timeframe: {INTERVAL}\n"
        f"Scanner: {'🟢 ON' if scanner_running else '🔴 OFF'}\n"
        f"Twelve Data: "
        f"{'🟢 CONNECTED' if TWELVE_DATA_API_KEY else '🔴 MISSING'}\n\n"
    )

    if chat_id:
        message += (
            f"🆔 Saved Chat ID: `{chat_id}`\n\n"
        )
    else:
        message += (
            "Send /start to automatically register "
            "your Telegram Chat ID.\n\n"
        )

    message += (
        "Commands:\n"
        "/start — Register Telegram\n"
        "/scan — Scan GOLD now\n"
        "/status — Bot status"
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
    )


# ============================================================
# TWELVE DATA
# ============================================================

def get_gold_data():

    if not TWELVE_DATA_API_KEY:

        logger.error(
            "TWELVE_DATA_API_KEY is missing."
        )

        return None

    url = "https://api.twelvedata.com/time_series"

    params = {
        "symbol": XAU_SYMBOL,
        "interval": INTERVAL,
        "outputsize": OUTPUT_SIZE,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON",
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=30,
        )

        if response.status_code != 200:

            logger.error(
                f"Twelve Data HTTP error: "
                f"{response.status_code}"
            )

            return None

        data = response.json()

        if "values" not in data:

            logger.error(
                f"Twelve Data error: {data}"
            )

            return None

        values = data["values"]

        if len(values) < 50:

            logger.error(
                "Not enough GOLD candles."
            )

            return None

        values = list(reversed(values))

        candles = []

        for item in values:

            try:

                candles.append(
                    {
                        "datetime": item["datetime"],
                        "open": float(item["open"]),
                        "high": float(item["high"]),
                        "low": float(item["low"]),
                        "close": float(item["close"]),
                    }
                )

            except Exception:
                continue

        return candles

    except Exception as e:

        logger.error(
            f"Gold data error: {e}"
        )

        return None


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

    avg_gain = sum(
        gains[:period]
    ) / period

    avg_loss = sum(
        losses[:period]
    ) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        high = current["high"]
        low = current["low"]
        previous_close = previous["close"]

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    atr = sum(
        true_ranges[:period]
    ) / period

    for tr in true_ranges[period:]:

        atr = (
            (atr * (period - 1))
            + tr
        ) / period

    return atr


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_gold(candles):

    closes = [
        candle["close"]
        for candle in candles
    ]

    highs = [
        candle["high"]
        for candle in candles
    ]

    lows = [
        candle["low"]
        for candle in candles
    ]

    price = closes[-1]

    ema20 = calculate_ema(
        closes,
        20,
    )

    ema50 = calculate_ema(
        closes,
        50,
    )

    rsi = calculate_rsi(
        closes,
        14,
    )

    atr = calculate_atr(
        candles,
        14,
    )

    if None in (
        ema20,
        ema50,
        rsi,
        atr,
    ):
        return None

    recent_high = max(
        highs[-20:]
    )

    recent_low = min(
        lows[-20:]
    )

    # ========================================================
    # TREND
    # ========================================================

    if (
        price > ema20
        and ema20 > ema50
    ):

        trend = "BULLISH 📈"

    elif (
        price < ema20
        and ema20 < ema50
    ):

        trend = "BEARISH 📉"

    else:

        trend = "RANGING ↔️"

    # ========================================================
    # SIGNAL
    # ========================================================

    buy_score = 0
    sell_score = 0

    # EMA structure
    if price > ema20:
        buy_score += 25

    if price > ema50:
        buy_score += 20

    if price < ema20:
        sell_score += 25

    if price < ema50:
        sell_score += 20

    # RSI
    if 50 <= rsi <= 68:
        buy_score += 20

    if 32 <= rsi <= 50:
        sell_score += 20

    # Momentum
    if len(closes) >= 4:

        if closes[-1] > closes[-2]:
            buy_score += 15

        if closes[-1] < closes[-2]:
            sell_score += 15

    # Structure
    if price > recent_high * 0.999:

        buy_score += 20

    if price < recent_low * 1.001:

        sell_score += 20

    # ========================================================
    # FINAL SIGNAL
    # ========================================================

    if buy_score >= sell_score:

        side = "BUY 🟢"
        score = buy_score

    else:

        side = "SELL 🔴"
        score = sell_score

    confidence = min(
        max(score, 50),
        95,
    )

    # ========================================================
    # TRADE LEVELS
    # ========================================================

    if side.startswith("BUY"):

        entry = price

        stop_loss = (
            price - atr * 1.5
        )

        tp1 = (
            price + atr * 1.0
        )

        tp2 = (
            price + atr * 2.0
        )

        tp3 = (
            price + atr * 3.0
        )

        # Pullback pending order
        pending_entry = (
            price - atr * 0.50
        )

        pending_type = "BUY LIMIT"

    else:

        entry = price

        stop_loss = (
            price + atr * 1.5
        )

        tp1 = (
            price - atr * 1.0
        )

        tp2 = (
            price - atr * 2.0
        )

        tp3 = (
            price - atr * 3.0
        )

        # Pullback pending order
        pending_entry = (
            price + atr * 0.50
        )

        pending_type = "SELL LIMIT"

    return {
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "trend": trend,
        "side": side,
        "confidence": confidence,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "pending_type": pending_type,
        "pending_entry": pending_entry,
        "recent_high": recent_high,
        "recent_low": recent_low,
    }


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(analysis):

    side = analysis["side"]

    price = analysis["price"]

    message = (
        "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"
        "🟡 *XAU/USD*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🚨 *AI MARKET SIGNAL*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Signal: *{side}*\n"
        f"🎯 Confidence: *{analysis['confidence']:.0f}%*\n\n"
        f"💰 Price: `${price:,.2f}`\n"
        f"📈 Trend: *{analysis['trend']}*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *TECHNICAL ANALYSIS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"EMA 20: `{analysis['ema20']:,.2f}`\n"
        f"EMA 50: `{analysis['ema50']:,.2f}`\n"
        f"RSI 14: `{analysis['rsi']:.1f}`\n"
        f"ATR 14: `{analysis['atr']:.2f}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 *TRADE LEVELS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢 Entry: `${analysis['entry']:,.2f}`\n"
        f"🛑 Stop Loss: `${analysis['stop_loss']:,.2f}`\n"
        f"🥇 TP1: `${analysis['tp1']:,.2f}`\n"
        f"🥈 TP2: `${analysis['tp2']:,.2f}`\n"
        f"🏆 TP3: `${analysis['tp3']:,.2f}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ *PENDING ORDER IDEA*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{analysis['pending_type']}: "
        f"`${analysis['pending_entry']:,.2f}`\n\n"
        f"⏱ Timeframe: *{INTERVAL}*\n"
        "📡 Data: *Twelve Data*\n\n"
        "⚠️ Market information is for analysis only.\n"
        "Not financial advice. Always manage risk."
    )

    return message


# ============================================================
# SCAN GOLD
# ============================================================

def scan_gold():

    logger.info("🔎 Scanning XAU/USD...")

    candles = get_gold_data()

    if not candles:

        logger.error(
            "Could not retrieve GOLD data."
        )

        return None

    analysis = analyze_gold(
        candles
    )

    if not analysis:

        logger.error(
            "Could not analyze GOLD."
        )

        return None

    logger.info(
        f"GOLD: {analysis['side']} | "
        f"Price: {analysis['price']:.2f} | "
        f"Confidence: {analysis['confidence']:.0f}%"
    )

    return analysis


# ============================================================
# /SCAN
# ============================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "🔎 *Scanning XAU/USD...*\n\n"
        "Please wait...",
        parse_mode="Markdown",
    )

    analysis = await asyncio.to_thread(
        scan_gold
    )

    if not analysis:

        await update.message.reply_text(
            "❌ I couldn't retrieve GOLD data right now.\n\n"
            "Check your Twelve Data API key and try again."
        )

        return

    message = format_signal(
        analysis
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
    )


# ============================================================
# AUTOMATIC SCANNER
# ============================================================

async def automatic_scanner():

    global scanner_running
    global last_signal_key
    global last_signal_time

    scanner_running = True

    logger.info(
        "🟢 Automatic GOLD scanner started."
    )

    while True:

        try:

            analysis = await asyncio.to_thread(
                scan_gold
            )

            if analysis:

                side = analysis["side"]

                price = analysis["price"]

                confidence = analysis["confidence"]

                # Signal key changes when direction/price zone changes
                price_zone = round(
                    price,
                    1,
                )

                signal_key = (
                    f"{side}_{price_zone}"
                )

                current_time = time.time()

                # Send if:
                # 1. New signal
                # 2. At least 30 minutes have passed
                #    since previous signal

                should_send = False

                if last_signal_key is None:

                    should_send = True

                elif signal_key != last_signal_key:

                    should_send = True

                elif (
                    current_time
                    - last_signal_time
                    >= 1800
                ):

                    should_send = True

                if should_send:

                    message = format_signal(
                        analysis
                    )

                    sent = await send_message(
                        message
                    )

                    if sent:

                        last_signal_key = signal_key
                        last_signal_time = current_time

                        logger.info(
                            "📨 GOLD signal sent to Telegram."
                        )

                    else:

                        logger.warning(
                            "⚠️ Signal generated, "
                            "but Telegram message was not sent."
                        )

        except Exception as e:

            logger.exception(
                f"Automatic scanner error: {e}"
            )

        await asyncio.sleep(
            SCAN_INTERVAL_SECONDS
        )


# ============================================================
# START BACKGROUND SCANNER
# ============================================================

def start_scanner_thread():

    def runner():

        try:

            asyncio.run(
                automatic_scanner()
            )

        except Exception as e:

            logger.exception(
                f"Scanner thread stopped: {e}"
            )

    thread = Thread(
        target=runner,
        daemon=True,
    )

    thread.start()

    logger.info(
        "🟢 Scanner background thread launched."
    )


# ============================================================
# TELEGRAM BOT
# ============================================================

async def post_init(
    application: Application,
):

    global telegram_application

    telegram_application = application

    logger.info(
        "🟢 Telegram application initialized."
    )

    saved_chat_id = load_chat_id()

    if saved_chat_id:

        logger.info(
            f"Saved Telegram Chat ID: "
            f"{saved_chat_id}"
        )

    else:

        logger.warning(
            "No Telegram Chat ID saved yet. "
            "Send /start to the bot."
        )


def create_telegram_application():

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "scan",
            scan_command,
        )
    )

    return application


# ============================================================
# MAIN
# ============================================================

def main():

    global telegram_application

    logger.info(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    logger.info(
        f"{BOT_NAME}"
    )

    logger.info(
        "🟢 Starting bot..."
    )

    logger.info(
        f"Market: {XAU_SYMBOL}"
    )

    logger.info(
        f"Timeframe: {INTERVAL}"
    )

    logger.info(
        f"Scan interval: "
        f"{SCAN_INTERVAL_SECONDS} seconds"
    )

    if not TELEGRAM_BOT_TOKEN:

        logger.error(
            "❌ TELEGRAM_BOT_TOKEN is missing."
        )

        return

    if not TWELVE_DATA_API_KEY:

        logger.error(
            "❌ TWELVE_DATA_API_KEY is missing."
        )

        return

    # Start Flask for Render
    flask_thread = Thread(
        target=run_flask,
        daemon=True,
    )

    flask_thread.start()

    logger.info(
        "🟢 Flask server started."
    )

    # Create Telegram application
    telegram_application = (
        create_telegram_application()
    )

    # Start automatic scanner
    start_scanner_thread()

    logger.info(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    logger.info(
        "👑 KING OF XAU_NAS IS ONLINE"
    )

    logger.info(
        "🟢 Telegram monitoring active."
    )

    logger.info(
        "🟡 XAU/USD scanner active."
    )

    logger.info(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    # Run Telegram bot
    telegram_application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
