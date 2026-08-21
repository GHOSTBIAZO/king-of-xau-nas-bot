import os
import json
import time
import asyncio
import logging
from threading import Thread
from datetime import datetime, timezone

import requests
import pandas as pd
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ============================================================
# 👑 KING OF XAU_NAS — MULTI MARKET TELEGRAM BOT
# ============================================================

BOT_NAME = "👑 KING OF XAU_NAS"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

PORT = int(os.getenv("PORT", "10000"))

INTERVAL = os.getenv("INTERVAL", "15min")
OUTPUT_SIZE = int(os.getenv("OUTPUT_SIZE", "200"))

# 70% gives the scanner more opportunities than the old 80%.
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "70"))

# Scan every 60 seconds.
SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))

CHAT_ID_FILE = "telegram_chat_id.json"

# ============================================================
# MARKETS
# ============================================================

SYMBOLS = {
    "XAU/USD": {
        "emoji": "🟡",
        "name": "Gold",
        "digits": 2,
    },

    "US100": {
        "emoji": "📈",
        "name": "Nasdaq 100",
        "digits": 2,
    },

    "US30": {
        "emoji": "🏛️",
        "name": "Dow Jones",
        "digits": 2,
    },

    "GBP/USD": {
        "emoji": "🇬🇧",
        "name": "GBP/USD",
        "digits": 5,
    },

    "GBP/JPY": {
        "emoji": "💷",
        "name": "GBP/JPY",
        "digits": 3,
    },

    "EUR/USD": {
        "emoji": "🇪🇺",
        "name": "EUR/USD",
        "digits": 5,
    },
}

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("KING_OF_XAU_NAS")

# ============================================================
# FLASK FOR RENDER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "KING OF XAU_NAS ONLINE"


@app.route("/health")
def health():
    return {
        "status": "online",
        "markets": len(SYMBOLS),
        "timeframe": INTERVAL,
    }


def run_web_server():
    app.run(
        host="0.0.0.0",
        port=PORT,
    )


# ============================================================
# CHAT ID
# ============================================================

def load_chat_id():

    try:

        if os.path.exists(CHAT_ID_FILE):

            with open(
                CHAT_ID_FILE,
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

                return data.get("chat_id")

    except Exception as error:

        logger.warning(
            "Could not load chat ID: %s",
            error,
        )

    return None


def save_chat_id(chat_id):

    try:

        with open(
            CHAT_ID_FILE,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                {
                    "chat_id": str(chat_id)
                },
                file,
            )

        logger.info(
            "Telegram Chat ID saved: %s",
            chat_id,
        )

    except Exception as error:

        logger.error(
            "Could not save Chat ID: %s",
            error,
        )


CHAT_ID = load_chat_id()

# Prevent duplicate notifications.
last_signals = {}


# ============================================================
# TELEGRAM SEND
# ============================================================

async def send_message(
    application,
    text,
    chat_id=None,
):

    target = chat_id or CHAT_ID

    if not target:

        logger.warning(
            "No Chat ID saved. Send /start to the bot."
        )

        return False

    try:

        # IMPORTANT:
        # No parse_mode.
        #
        # This fixes:
        # BadRequest:
        # can't parse entities

        await application.bot.send_message(
            chat_id=target,
            text=text,
        )

        return True

    except Exception as error:

        logger.error(
            "Telegram send error: %s",
            error,
        )

        return False


# ============================================================
# /START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    global CHAT_ID

    if not update.effective_chat:
        return

    if not update.message:
        return

    CHAT_ID = str(
        update.effective_chat.id
    )

    save_chat_id(CHAT_ID)

    message = (
        "👑 KING OF XAU_NAS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 BOT ONLINE\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "Your Telegram Chat ID has been saved.\n\n"

        "📊 MARKETS\n"
        "🟡 XAU/USD — Gold\n"
        "📈 US100 — Nasdaq 100\n"
        "🏛️ US30 — Dow Jones\n"
        "🇬🇧 GBP/USD\n"
        "💷 GBP/JPY\n"
        "🇪🇺 EUR/USD\n\n"

        f"⏱ Timeframe: {INTERVAL}\n"
        f"🎯 Minimum confidence: {MIN_CONFIDENCE}%\n"
        "📡 Data: Twelve Data\n\n"

        "COMMANDS\n"
        "/status\n"
        "/watchlist\n"
        "/start\n\n"

        "👑 KING OF XAU_NAS IS READY."
    )

    await update.message.reply_text(
        message
    )


# ============================================================
# /STATUS
# ============================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    message = (
        "👑 KING OF XAU_NAS — STATUS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "🟢 Telegram: CONNECTED\n"
        "🟢 Scanner: RUNNING\n"
        "🟢 Market Engine: ACTIVE\n\n"

        f"📊 Markets: {len(SYMBOLS)}\n"
        f"⏱ Timeframe: {INTERVAL}\n"
        f"🎯 Minimum confidence: {MIN_CONFIDENCE}%\n"
        "📡 Data: Twelve Data\n\n"

        "MONITORING:\n"
        "🟡 XAU/USD\n"
        "📈 US100\n"
        "🏛️ US30\n"
        "🇬🇧 GBP/USD\n"
        "💷 GBP/JPY\n"
        "🇪🇺 EUR/USD"
    )

    await update.message.reply_text(
        message
    )


# ============================================================
# /WATCHLIST
# ============================================================

async def watchlist_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    lines = [
        "👑 KING OF XAU_NAS — WATCHLIST",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for symbol, info in SYMBOLS.items():

        lines.append(
            f"{info['emoji']} "
            f"{symbol} — "
            f"{info['name']}"
        )

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━━━",
            f"⏱ Timeframe: {INTERVAL}",
            f"🎯 Minimum confidence: {MIN_CONFIDENCE}%",
        ]
    )

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# TELEGRAM ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context,
):

    logger.error(
        "Telegram error: %s",
        context.error,
    )


# ============================================================
# TWELVE DATA
# ============================================================

def fetch_market_data(symbol):

    if not TWELVE_DATA_API_KEY:

        raise RuntimeError(
            "TWELVE_DATA_API_KEY is missing."
        )

    url = (
        "https://api.twelvedata.com/"
        "time_series"
    )

    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "outputsize": OUTPUT_SIZE,
        "apikey": TWELVE_DATA_API_KEY,
    }

    response = requests.get(
        url,
        params=params,
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    if "values" not in data:

        raise RuntimeError(
            data.get(
                "message",
                f"No data for {symbol}",
            )
        )

    df = pd.DataFrame(
        data["values"]
    )

    required = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
    ]

    missing = [
        column
        for column in required
        if column not in df.columns
    ]

    if missing:

        raise RuntimeError(
            f"{symbol}: missing columns "
            f"{missing}"
        )

    for column in [
        "open",
        "high",
        "low",
        "close",
    ]:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    df = df.dropna(
        subset=[
            "open",
            "high",
            "low",
            "close",
        ]
    )

    # Twelve Data normally returns
    # newest candle first.

    df = (
        df
        .iloc[::-1]
        .reset_index(drop=True)
    )

    if len(df) < 60:

        raise RuntimeError(
            f"{symbol}: only "
            f"{len(df)} candles available."
        )

    return df


# ============================================================
# INDICATORS
# ============================================================

def add_indicators(df):

    df = df.copy()

    # EMA 20

    df["ema20"] = (
        df["close"]
        .ewm(
            span=20,
            adjust=False,
        )
        .mean()
    )

    # EMA 50

    df["ema50"] = (
        df["close"]
        .ewm(
            span=50,
            adjust=False,
        )
        .mean()
    )

    # RSI 14

    delta = df["close"].diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = (
        gain
        .ewm(
            alpha=1 / 14,
            adjust=False,
        )
        .mean()
    )

    avg_loss = (
        loss
        .ewm(
            alpha=1 / 14,
            adjust=False,
        )
        .mean()
    )

    rs = (
        avg_gain /
        avg_loss.replace(
            0,
            float("nan"),
        )
    )

    df["rsi"] = (
        100 -
        (
            100 /
            (1 + rs)
        )
    )

    df["rsi"] = (
        df["rsi"]
        .fillna(50)
    )

    # ATR 14

    previous_close = (
        df["close"]
        .shift(1)
    )

    tr1 = (
        df["high"] -
        df["low"]
    )

    tr2 = (
        df["high"] -
        previous_close
    ).abs()

    tr3 = (
        df["low"] -
        previous_close
    ).abs()

    true_range = pd.concat(
        [
            tr1,
            tr2,
            tr3,
        ],
        axis=1,
    ).max(axis=1)

    df["atr"] = (
        true_range
        .ewm(
            alpha=1 / 14,
            adjust=False,
        )
        .mean()
    )

    return df


# ============================================================
# BOS
# ============================================================

def detect_bos(df):

    if len(df) < 10:
        return None

    last = df.iloc[-1]

    previous_high = (
        df["high"]
        .iloc[-6:-1]
        .max()
    )

    previous_low = (
        df["low"]
        .iloc[-6:-1]
        .min()
    )

    if last["close"] > previous_high:
        return "BUY"

    if last["close"] < previous_low:
        return "SELL"

    return None


# ============================================================
# CHOCH
# ============================================================

def detect_choch(df):

    if len(df) < 10:
        return None

    recent = df.iloc[-8:-1]

    last = df.iloc[-1]

    if last["close"] > recent["high"].max():
        return "BUY"

    if last["close"] < recent["low"].min():
        return "SELL"

    return None


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def detect_liquidity_sweep(df):

    if len(df) < 20:
        return None

    last = df.iloc[-1]

    previous = df.iloc[-16:-1]

    previous_high = (
        previous["high"].max()
    )

    previous_low = (
        previous["low"].min()
    )

    if (
        last["high"] > previous_high
        and
        last["close"] < previous_high
    ):
        return "SELL"

    if (
        last["low"] < previous_low
        and
        last["close"] > previous_low
    ):
        return "BUY"

    return None


# ============================================================
# FVG
# ============================================================

def detect_fvg(df):

    if len(df) < 5:
        return None

    c1 = df.iloc[-3]
    c2 = df.iloc[-2]
    c3 = df.iloc[-1]

    if (
        c3["low"] > c1["high"]
        and
        c2["close"] > c2["open"]
    ):
        return "BUY"

    if (
        c3["high"] < c1["low"]
        and
        c2["close"] < c2["open"]
    ):
        return "SELL"

    return None


# ============================================================
# MOMENTUM
# ============================================================

def detect_momentum(df):

    last = df.iloc[-1]

    previous = df.iloc[-2]

    if last["close"] > previous["close"]:
        return "BUY"

    if last["close"] < previous["close"]:
        return "SELL"

    return None


# ============================================================
# CONFIDENCE
# ============================================================

def calculate_signal(df):

    last = df.iloc[-1]

    price = float(last["close"])
    ema20 = float(last["ema20"])
    ema50 = float(last["ema50"])
    rsi = float(last["rsi"])
    atr = float(last["atr"])

    if atr <= 0:
        return None, 0, "Invalid ATR"

    bos = detect_bos(df)
    choch = detect_choch(df)
    liquidity = detect_liquidity_sweep(df)
    fvg = detect_fvg(df)
    momentum = detect_momentum(df)

    buy_score = 0
    sell_score = 0

    # TREND — 20

    if ema20 > ema50:
        buy_score += 20

    elif ema20 < ema50:
        sell_score += 20

    # RSI — 15
    #
    # Broadened from the old strict
    # 55/45 zones.

    if 52 <= rsi <= 72:
        buy_score += 15

    elif 28 <= rsi <= 48:
        sell_score += 15

    # BOS — 15

    if bos == "BUY":
        buy_score += 15

    elif bos == "SELL":
        sell_score += 15

    # CHOCH — 15

    if choch == "BUY":
        buy_score += 15

    elif choch == "SELL":
        sell_score += 15

    # FVG — 15

    if fvg == "BUY":
        buy_score += 15

    elif fvg == "SELL":
        sell_score += 15

    # LIQUIDITY — 10

    if liquidity == "BUY":
        buy_score += 10

    elif liquidity == "SELL":
        sell_score += 10

    # MOMENTUM — 10

    if momentum == "BUY":
        buy_score += 10

    elif momentum == "SELL":
        sell_score += 10

    # Select strongest side.

    if buy_score >= sell_score:

        side = "BUY"
        confidence = buy_score

    else:

        side = "SELL"
        confidence = sell_score

    # Log candidate even if it does not
    # qualify.

    if confidence < MIN_CONFIDENCE:

        return (
            None,
            confidence,
            f"{side} candidate {confidence}%"
            f" — below {MIN_CONFIDENCE}%",
        )

    # ATR-based levels.

    if side == "BUY":

        sl = price - atr * 1.5
        tp1 = price + atr * 2.0
        tp2 = price + atr * 3.0
        tp3 = price + atr * 5.0

    else:

        sl = price + atr * 1.5
        tp1 = price - atr * 2.0
        tp2 = price - atr * 3.0
        tp3 = price - atr * 5.0

    signal = {

        "side": side,

        "confidence": confidence,

        "price": price,

        "sl": sl,

        "tp1": tp1,

        "tp2": tp2,

        "tp3": tp3,

        "ema20": ema20,

        "ema50": ema50,

        "rsi": rsi,

        "atr": atr,

        "bos": bos,

        "choch": choch,

        "fvg": fvg,

        "liquidity": liquidity,

        "momentum": momentum,
    }

    return (
        signal,
        confidence,
        f"{side} QUALIFYING SIGNAL",
    )


# ============================================================
# PRICE FORMAT
# ============================================================

def format_price(
    symbol,
    value,
):

    digits = SYMBOLS[
        symbol
    ]["digits"]

    return (
        f"{value:,.{digits}f}"
    )


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def build_signal_message(
    symbol,
    signal,
):

    info = SYMBOLS[symbol]

    side = signal["side"]

    direction = (
        "🟢"
        if side == "BUY"
        else "🔴"
    )

    timestamp = (
        datetime
        .now(timezone.utc)
        .strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    )

    def mark(value):
        return (
            "✅"
            if value == side
            else "—"
        )

    return (
        f"{BOT_NAME}\n"
        f"{info['emoji']} "
        f"{symbol} — "
        f"{info['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"

        f"{direction} "
        f"SIGNAL CONFIRMED — "
        f"{side}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        "📌 Setup: INSTITUTIONAL\n"
        "🎯 Stage: CONFIRMED\n"

        f"💯 Confidence: "
        f"{signal['confidence']}%\n"

        f"💰 Entry: "
        f"{format_price(symbol, signal['price'])}\n"

        f"🛑 Stop Loss: "
        f"{format_price(symbol, signal['sl'])}\n"

        f"🎯 TP1: "
        f"{format_price(symbol, signal['tp1'])}\n"

        f"🎯 TP2: "
        f"{format_price(symbol, signal['tp2'])}\n"

        f"🎯 TP3: "
        f"{format_price(symbol, signal['tp3'])}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"📊 EMA20: "
        f"{format_price(symbol, signal['ema20'])}\n"

        f"📊 EMA50: "
        f"{format_price(symbol, signal['ema50'])}\n"

        f"📈 RSI14: "
        f"{signal['rsi']:.1f}\n"

        f"⚡ ATR14: "
        f"{format_price(symbol, signal['atr'])}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"🏗 BOS: "
        f"{mark(signal['bos'])}\n"

        f"🔄 CHoCH: "
        f"{mark(signal['choch'])}\n"

        f"💧 Liquidity Sweep: "
        f"{mark(signal['liquidity'])}\n"

        f"📦 FVG: "
        f"{mark(signal['fvg'])}\n"

        f"⚡ Momentum: "
        f"{mark(signal['momentum'])}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"⏱ Timeframe: "
        f"{INTERVAL}\n"

        f"🕐 {timestamp}\n\n"

        "⚠️ Analysis only — "
        "not financial advice."
    )


# ============================================================
# SCAN ONE MARKET
# ============================================================

async def analyze_and_send(
    application,
    symbol,
):

    global last_signals

    try:

        df = fetch_market_data(
            symbol
        )

        df = add_indicators(
            df
        )

        signal, confidence, reason = (
            calculate_signal(df)
        )

        last = df.iloc[-1]

        logger.info(
            "%s → %s | "
            "Price=%s | "
            "RSI=%.1f | "
            "EMA20=%s | "
            "EMA50=%s",
            symbol,
            reason,
            format_price(
                symbol,
                float(last["close"]),
            ),
            float(last["rsi"]),
            format_price(
                symbol,
                float(last["ema20"]),
            ),
            format_price(
                symbol,
                float(last["ema50"]),
            ),
        )

        if not signal:
            return

        candle_time = str(
            df.iloc[-1]["datetime"]
        )

        signal_key = (
            f"{symbol}:"
            f"{candle_time}:"
            f"{signal['side']}"
        )

        if (
            last_signals.get(symbol)
            ==
            signal_key
        ):

            logger.info(
                "%s → duplicate skipped",
                symbol,
            )

            return

        last_signals[symbol] = (
            signal_key
        )

        message = (
            build_signal_message(
                symbol,
                signal,
            )
        )

        sent = await send_message(
            application,
            message,
        )

        if sent:

            logger.info(
                "%s → %s SIGNAL SENT "
                "at %s%%",
                symbol,
                signal["side"],
                signal["confidence"],
            )

    except Exception as error:

        logger.warning(
            "%s → scan failed: %s",
            symbol,
            error,
        )


# ============================================================
# SCANNER
# ============================================================

async def scanner_loop(
    application,
):

    logger.info(
        "=============================================="
    )

    logger.info(
        "👑 KING OF XAU_NAS SCANNER STARTED"
    )

    logger.info(
        "Markets: %s",
        ", ".join(
            SYMBOLS.keys()
        ),
    )

    logger.info(
        "Timeframe: %s",
        INTERVAL,
    )

    logger.info(
        "Minimum confidence: %s%%",
        MIN_CONFIDENCE,
    )

    logger.info(
        "=============================================="
    )

    while True:

        scan_started = (
            time.time()
        )

        for symbol in SYMBOLS:

            await analyze_and_send(
                application,
                symbol,
            )

            # Protect API rate limits.

            await asyncio.sleep(2)

        elapsed = (
            time.time()
            -
            scan_started
        )

        wait_time = max(
            5,
            SCAN_SECONDS -
            int(elapsed),
        )

        logger.info(
            "Full scan complete. "
            "Next scan in %s seconds.",
            wait_time,
        )

        await asyncio.sleep(
            wait_time
        )


# ============================================================
# POST INIT
# ============================================================

async def post_init(
    application,
):

    asyncio.create_task(
        scanner_loop(
            application
        )
    )

    logger.info(
        "Background scanner started."
    )


# ============================================================
# VALIDATE
# ============================================================

def validate_config():

    missing = []

    if not TELEGRAM_BOT_TOKEN:

        missing.append(
            "TELEGRAM_BOT_TOKEN"
        )

    if not TWELVE_DATA_API_KEY:

        missing.append(
            "TWELVE_DATA_API_KEY"
        )

    if missing:

        raise RuntimeError(
            "Missing Render environment "
            "variable(s): "
            +
            ", ".join(missing)
        )


# ============================================================
# MAIN
# ============================================================

def main():

    validate_config()

    logger.info(
        "=============================================="
    )

    logger.info(
        "%s",
        BOT_NAME,
    )

    logger.info(
        "Starting Telegram bot..."
    )

    logger.info(
        "Markets: %s",
        ", ".join(
            SYMBOLS.keys()
        ),
    )

    logger.info(
        "Timeframe: %s",
        INTERVAL,
    )

    logger.info(
        "Minimum confidence: %s%%",
        MIN_CONFIDENCE,
    )

    logger.info(
        "=============================================="
    )

    # Render web server.

    web_thread = Thread(
        target=run_web_server,
        daemon=True,
    )

    web_thread.start()

    # Telegram application.

    application = (
        Application
        .builder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
        .post_init(
            post_init
        )
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
            "watchlist",
            watchlist_command,
        )
    )

    # FIX:
    # Prevents:
    # "No error handlers are registered"

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Telegram polling starting..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    main()
