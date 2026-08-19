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
# STRICT AI-STYLE SIGNAL ENGINE
# ============================================================

BOT_NAME = "👑 KING OF XAU_NAS — GOLD"

# ============================================================
# ENVIRONMENT
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TWELVE_DATA_API_KEY = os.getenv(
    "TWELVE_DATA_API_KEY",
    ""
).strip()

PORT = int(
    os.getenv("PORT", "10000")
)

# ============================================================
# MARKET SETTINGS
# ============================================================

XAU_SYMBOL = "XAU/USD"

INTERVAL = "15min"

OUTPUT_SIZE = 100

SCAN_INTERVAL_SECONDS = 600

# ============================================================
# FILE
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
# GLOBALS
# ============================================================

telegram_application = None

chat_id_lock = Lock()

last_signal_key = None

last_signal_time = 0

scanner_running = False


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():

    return f"""
    <html>
        <head>
            <title>King of XAU_NAS</title>
        </head>

        <body style="
            background:#111;
            color:white;
            font-family:Arial;
            text-align:center;
            padding-top:50px;
        ">

            <h1>{BOT_NAME}</h1>

            <h2>🟢 BOT ONLINE</h2>

            <p>Market: XAU/USD</p>
            <p>Timeframe: 15 Minutes</p>
            <p>Signal Engine: STRICT</p>

        </body>
    </html>
    """


@app.route("/health")
def health():

    return {
        "status": "online",
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

        logger.error(
            f"Flask error: {e}"
        )


# ============================================================
# CHAT ID
# ============================================================

def load_chat_id():

    try:

        if not os.path.exists(
            CHAT_ID_FILE
        ):
            return None

        with open(
            CHAT_ID_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        chat_id = data.get(
            "chat_id"
        )

        if chat_id:

            return str(chat_id)

    except Exception as e:

        logger.error(
            f"Chat ID load error: {e}"
        )

    return None


def save_chat_id(chat_id):

    try:

        with chat_id_lock:

            with open(
                CHAT_ID_FILE,
                "w",
                encoding="utf-8",
            ) as file:

                json.dump(
                    {
                        "chat_id": str(
                            chat_id
                        ),
                        "saved_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    },
                    file,
                    indent=4,
                )

        logger.info(
            f"Telegram Chat ID saved: {chat_id}"
        )

        return True

    except Exception as e:

        logger.error(
            f"Chat ID save error: {e}"
        )

        return False


# ============================================================
# TELEGRAM SEND
# ============================================================

async def send_message(message):

    global telegram_application

    chat_id = load_chat_id()

    if not chat_id:

        logger.warning(
            "No Chat ID saved. "
            "Send /start first."
        )

        return False

    if telegram_application is None:

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
            f"Telegram error: {e}"
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

    username = "Telegram User"

    if update.effective_user:

        if update.effective_user.username:

            username = (
                "@"
                + update.effective_user.username
            )

    saved = save_chat_id(
        chat_id
    )

    if saved:

        message = (
            "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"
            "🟢 *BOT CONNECTED*\n\n"
            f"👤 User: {username}\n"
            f"🆔 Chat ID: `{chat_id}`\n\n"
            "✅ Your Telegram Chat ID has been "
            "automatically detected and saved.\n\n"
            "🟡 Market: XAU/USD\n"
            "⏱ Timeframe: 15 Minutes\n"
            "🤖 Automatic Scanner: ON\n"
            "🧠 Signal Engine: STRICT\n\n"
            "Use /scan for a live GOLD scan.\n"
            "Use /status for bot status."
        )

    else:

        message = (
            "⚠️ Chat ID detected
