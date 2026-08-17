import os
import logging
import requests
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# =========================
# SETTINGS
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

PORT = int(os.getenv("PORT", 10000))

# =========================
# LOGGING
# =========================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# =========================
# FLASK SERVER
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "King of XAU_NAS Bot is running!"


def run_web_server():
    app.run(host="0.0.0.0", port=PORT)


# =========================
# TWELVE DATA
# =========================

def get_price(symbol):
    if not TWELVE_DATA_API_KEY:
        return None, "Twelve Data API key is missing."

    url = "https://api.twelvedata.com/price"

    params = {
        "symbol": symbol,
        "apikey": TWELVE_DATA_API_KEY,
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()

        if "price" in data:
            return float(data["price"]), None

        return None, data.get("message", "Unable to get market price.")

    except Exception as e:
        logger.error("Twelve Data error: %s", e)
        return None, "Could not connect to Twelve Data."


# =========================
# TELEGRAM COMMANDS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "👑 KING OF XAU_NAS 👑\n\n"
        "Welcome!\n\n"
        "📊 Market scanner bot\n\n"
        "Commands:\n"
        "/gold - XAU/USD price\n"
        "/nasdaq - Nasdaq price\n"
        "/market - Check both markets\n"
        "/help - Show commands\n\n"
        "⚠️ Market information is for analysis only."
    )

    await update.message.reply_text(message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "📚 COMMANDS\n\n"
        "/start - Start the bot\n"
        "/gold - Check XAU/USD\n"
        "/nasdaq - Check Nasdaq\n"
        "/market - Check both\n"
    )

    await update.message.reply_text(message)


async def gold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price, error = get_price("XAU/USD")

    if error:
        await update.message.reply_text(
            f"❌ Gold data error:\n{error}"
        )
        return

    message = (
        "🥇 XAU/USD GOLD\n\n"
        f"💰 Current price: ${price:,.2f}\n\n"
        "📊 Market data received from Twelve Data.\n"
        "⚠️ This is not financial advice."
    )

    await update.message.reply_text(message)


async def nasdaq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price, error = get_price("IXIC")

    if error:
        await update.message.reply_text(
            f"❌ Nasdaq data error:\n{error}"
        )
        return

    message = (
        "📈 NASDAQ\n\n"
        f"💰 Current price: {price:,.2f}\n\n"
        "📊 Market data received from Twelve Data.\n"
        "⚠️ This is not financial advice."
    )

    await update.message.reply_text(message)


async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gold_price, gold_error = get_price("XAU/USD")
    nasdaq_price, nasdaq_error = get_price("IXIC")

    message = "👑 KING OF XAU_NAS MARKET SCANNER 👑\n\n"

    if gold_price is not None:
        message += f"🥇 XAU/USD: ${gold_price:,.2f}\n"
    else:
        message += f"🥇 XAU/USD: ❌ {gold_error}\n"

    if nasdaq_price is not None:
        message += f"📈 NASDAQ: {nasdaq_price:,.2f}\n"
    else:
        message += f"📈 NASDAQ: ❌ {nasdaq_error}\n"

    message += (
        "\n📊 Live market data\n"
        "⚠️ Analysis only — not financial advice."
    )

    await update.message.reply_text(message)


# =========================
# MAIN
# =========================

def main():

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing.")
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")

    if not TWELVE_DATA_API_KEY:
        logger.warning("TWELVE_DATA_API_KEY is missing.")

    # Start Flask server
    web_thread = Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()

    # Create Telegram application
    application = Application.builder().token(
        TELEGRAM_BOT_TOKEN
    ).build()

    # Commands
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("gold", gold)
    )

    application.add_handler(
        CommandHandler("nasdaq", nasdaq)
    )

    application.add_handler(
        CommandHandler("market", market)
    )

    logger.info("King of XAU_NAS bot is starting...")

    # Start Telegram polling
    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
