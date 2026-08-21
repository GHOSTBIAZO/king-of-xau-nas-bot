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
# 👑 KING OF XAU_NAS — FULL MULTI-MARKET TELEGRAM BOT
# ============================================================

BOT_NAME = "👑 KING OF XAU_NAS"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

PORT = int(os.getenv("PORT", "10000"))

TIMEFRAME = os.getenv("INTERVAL", "15min")
OUTPUT_SIZE = int(os.getenv("OUTPUT_SIZE", "200"))

NORMAL_CONFIDENCE = int(
    os.getenv("NORMAL_CONFIDENCE", "70")
)

SCALP_CONFIDENCE = int(
    os.getenv("SCALP_CONFIDENCE", "60")
)

SCAN_SECONDS = int(
    os.getenv("SCAN_SECONDS", "60")
)

CHAT_ID_FILE = "telegram_chat_id.json"

# ============================================================
# MARKETS
# ============================================================

MARKETS = {
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
# GLOBAL STATE
# ============================================================

MODE = "NORMAL"

CHAT_ID = None

LAST_SIGNALS = {}

LATEST_RESULTS = {}

SCANNER_RUNNING = False

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("KING_OF_XAU_NAS")

# ============================================================
# FLASK / RENDER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "KING OF XAU_NAS ONLINE"


@app.route("/health")
def health():

    return {
        "status": "online",
        "bot": BOT_NAME,
        "mode": MODE,
        "markets": len(MARKETS),
        "timeframe": TIMEFRAME,
        "scanner": SCANNER_RUNNING,
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
            "Chat ID load error: %s",
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
            "Chat ID saved: %s",
            chat_id,
        )

    except Exception as error:

        logger.error(
            "Chat ID save error: %s",
            error,
        )


CHAT_ID = load_chat_id()

# ============================================================
# TELEGRAM SEND
# ============================================================

async def send_telegram(
    application,
    message,
    chat_id=None,
):

    target = chat_id or CHAT_ID

    if not target:

        logger.warning(
            "No Telegram Chat ID. "
            "Send /start first."
        )

        return False

    try:

        # IMPORTANT:
        # No Markdown.
        # No HTML.
        #
        # This prevents:
        # BadRequest: can't parse entities

        await application.bot.send_message(
            chat_id=target,
            text=message,
        )

        return True

    except Exception as error:

        logger.error(
            "Telegram error: %s",
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

    if not update.message:
        return

    if not update.effective_chat:
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

        "Telegram Chat ID saved successfully.\n\n"

        "📊 MARKETS\n"
        "🟡 XAU/USD — Gold\n"
        "📈 US100 — Nasdaq 100\n"
        "🏛️ US30 — Dow Jones\n"
        "🇬🇧 GBP/USD\n"
        "💷 GBP/JPY\n"
        "🇪🇺 EUR/USD\n\n"

        f"⚙️ Mode: {MODE}\n"
        f"⏱ Timeframe: {TIMEFRAME}\n\n"

        "COMMANDS\n"
        "/status — bot status\n"
        "/watchlist — markets\n"
        "/scan — normal scan now\n"
        "/scalp — scalp scan now\n"
        "/normal — normal mode\n"
        "/signals — latest results\n"
        "/start — register chat\n\n"

        "👑 KING OF XAU_NAS READY."
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
        "🟢 Bot: ONLINE\n"
        "🟢 Scanner: RUNNING\n"
        "🟢 Market Engine: ACTIVE\n\n"

        f"⚙️ Mode: {MODE}\n"
        f"⏱ Timeframe: {TIMEFRAME}\n"
        f"📊 Markets: {len(MARKETS)}\n"
        f"🎯 Normal threshold: "
        f"{NORMAL_CONFIDENCE}%\n"
        f"⚡ Scalp threshold: "
        f"{SCALP_CONFIDENCE}%\n\n"

        "Markets monitored:\n"
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

    for symbol, info in MARKETS.items():

        lines.append(
            f"{info['emoji']} "
            f"{symbol} — "
            f"{info['name']}"
        )

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━━━",
            f"⚙️ Current mode: {MODE}",
            f"⏱ Timeframe: {TIMEFRAME}",
        ]
    )

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# /NORMAL
# ============================================================

async def normal_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    global MODE

    MODE = "NORMAL"

    if not update.message:
        return

    await update.message.reply_text(
        "👑 KING OF XAU_NAS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 NORMAL MODE ACTIVATED\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Confidence threshold: "
        f"{NORMAL_CONFIDENCE}%\n"
        f"⏱ Timeframe: {TIMEFRAME}\n\n"
        "Normal scanning will continue automatically."
    )


# ============================================================
# /SCALP
# ============================================================

async def scalp_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    global MODE

    MODE = "SCALP"

    if not update.message:
        return

    await update.message.reply_text(
        "👑 KING OF XAU_NAS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ SCALPING MODE ACTIVATED\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Confidence threshold: "
        f"{SCALP_CONFIDENCE}%\n"
        f"⏱ Timeframe: {TIMEFRAME}\n\n"
        "⚡ Faster setups enabled.\n"
        "⚠️ Scalping carries higher risk."
    )

    # Immediately scan after switching.

    asyncio.create_task(
        manual_scan(
            context.application,
            "SCALP",
        )
    )


# ============================================================
# /SCAN
# ============================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    global MODE

    MODE = "NORMAL"

    if not update.message:
        return

    await update.message.reply_text(
        "🔎 KING OF XAU_NAS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📡 NORMAL SCAN STARTED\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Scanning all markets..."
    )

    asyncio.create_task(
        manual_scan(
            context.application,
            "NORMAL",
        )
    )


# ============================================================
# /SIGNALS
# ============================================================

async def signals_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    if not LATEST_RESULTS:

        await update.message.reply_text(
            "👑 KING OF XAU_NAS\n\n"
            "No market results yet.\n"
            "Use /scan to start a scan."
        )

        return

    lines = [
        "👑 KING OF XAU_NAS — LATEST",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for symbol in MARKETS:

        result = LATEST_RESULTS.get(
            symbol
        )

        if not result:
            continue

        lines.append(
            f"{result['emoji']} "
            f"{symbol}: "
            f"{result['text']}"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context,
):

    logger.error(
        "Telegram handler error: %s",
        context.error,
    )


# ============================================================
# DATA FETCH
# ============================================================

def fetch_market_data(symbol):

    if not TWELVE_DATA_API_KEY:

        raise RuntimeError(
            "TWELVE_DATA_API_KEY is missing."
        )

    response = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": symbol,
            "interval": TIMEFRAME,
            "outputsize": OUTPUT_SIZE,
            "apikey": TWELVE_DATA_API_KEY,
        },
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    if "values" not in data:

        raise RuntimeError(
            data.get(
                "message",
                f"No data returned for {symbol}",
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

    for column in required:

        if column not in df.columns:

            raise RuntimeError(
                f"{symbol}: missing {column}"
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

    df = (
        df
        .iloc[::-1]
        .reset_index(drop=True)
    )

    if len(df) < 60:

        raise RuntimeError(
            f"{symbol}: insufficient candles"
        )

    return df


# ============================================================
# INDICATORS
# ============================================================

def add_indicators(df):

    df = df.copy()

    df["ema20"] = (
        df["close"]
        .ewm(
            span=20,
            adjust=False,
        )
        .mean()
    )

    df["ema50"] = (
        df["close"]
        .ewm(
            span=50,
            adjust=False,
        )
        .mean()
    )

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
        100 /
        (1 + rs)
    )

    df["rsi"] = (
        df["rsi"]
        .fillna(50)
    )

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
# PRICE ACTION
# ============================================================

def detect_bos(df):

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

    last = df.iloc[-1]

    if last["close"] > previous_high:
        return "BUY"

    if last["close"] < previous_low:
        return "SELL"

    return None


def detect_choch(df):

    recent = df.iloc[-8:-1]

    last = df.iloc[-1]

    if last["close"] > recent["high"].max():
        return "BUY"

    if last["close"] < recent["low"].min():
        return "SELL"

    return None


def detect_liquidity(df):

    recent = df.iloc[-16:-1]

    last = df.iloc[-1]

    high = recent["high"].max()
    low = recent["low"].min()

    if (
        last["high"] > high
        and
        last["close"] < high
    ):
        return "SELL"

    if (
        last["low"] < low
        and
        last["close"] > low
    ):
        return "BUY"

    return None


def detect_fvg(df):

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


def detect_momentum(df):

    last = df.iloc[-1]
    previous = df.iloc[-2]

    if last["close"] > previous["close"]:
        return "BUY"

    if last["close"] < previous["close"]:
        return "SELL"

    return None


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal(
    df,
    mode,
):

    last = df.iloc[-1]

    price = float(
        last["close"]
    )

    ema20 = float(
        last["ema20"]
    )

    ema50 = float(
        last["ema50"]
    )

    rsi = float(
        last["rsi"]
    )

    atr = float(
        last["atr"]
    )

    bos = detect_bos(df)
    choch = detect_choch(df)
    liquidity = detect_liquidity(df)
    fvg = detect_fvg(df)
    momentum = detect_momentum(df)

    buy = 0
    sell = 0

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    if ema20 > ema50:
        buy += 20

    elif ema20 < ema50:
        sell += 20

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 52 <= rsi <= 72:
        buy += 15

    elif 28 <= rsi <= 48:
        sell += 15

    # --------------------------------------------------------
    # BOS
    # --------------------------------------------------------

    if bos == "BUY":
        buy += 15

    elif bos == "SELL":
        sell += 15

    # --------------------------------------------------------
    # CHOCH
    # --------------------------------------------------------

    if choch == "BUY":
        buy += 15

    elif choch == "SELL":
        sell += 15

    # --------------------------------------------------------
    # FVG
    # --------------------------------------------------------

    if fvg == "BUY":
        buy += 15

    elif fvg == "SELL":
        sell += 15

    # --------------------------------------------------------
    # LIQUIDITY
    # --------------------------------------------------------

    if liquidity == "BUY":
        buy += 10

    elif liquidity == "SELL":
        sell += 10

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if momentum == "BUY":
        buy += 10

    elif momentum == "SELL":
        sell += 10

    # --------------------------------------------------------
    # MODE THRESHOLD
    # --------------------------------------------------------

    if mode == "SCALP":

        threshold = SCALP_CONFIDENCE

    else:

        threshold = NORMAL_CONFIDENCE

    if buy >= sell:

        side = "BUY"
        confidence = buy

    else:

        side = "SELL"
        confidence = sell

    if confidence < threshold:

        return (
            None,
            confidence,
            f"{side} candidate {confidence}% "
            f"(threshold {threshold}%)",
        )

    # --------------------------------------------------------
    # TARGETS
    # --------------------------------------------------------

    if mode == "SCALP":

        sl_multiplier = 1.0
        tp1_multiplier = 1.2
        tp2_multiplier = 1.8
        tp3_multiplier = 2.5

    else:

        sl_multiplier = 1.5
        tp1_multiplier = 2.0
        tp2_multiplier = 3.0
        tp3_multiplier = 5.0

    if side == "BUY":

        sl = (
            price -
            atr * sl_multiplier
        )

        tp1 = (
            price +
            atr * tp1_multiplier
        )

        tp2 = (
            price +
            atr * tp2_multiplier
        )

        tp3 = (
            price +
            atr * tp3_multiplier
        )

    else:

        sl = (
            price +
            atr * sl_multiplier
        )

        tp1 = (
            price -
            atr * tp1_multiplier
        )

        tp2 = (
            price -
            atr * tp2_multiplier
        )

        tp3 = (
            price -
            atr * tp3_multiplier
        )

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
        "liquidity": liquidity,
        "fvg": fvg,
        "momentum": momentum,
        "mode": mode,
    }

    return (
        signal,
        confidence,
        f"{side} SIGNAL",
    )


# ============================================================
# PRICE FORMAT
# ============================================================

def fmt(
    symbol,
    value,
):

    digits = MARKETS[
        symbol
    ]["digits"]

    return (
        f"{value:,.{digits}f}"
    )


# ============================================================
# BUILD SIGNAL
# ============================================================

def build_signal_message(
    symbol,
    signal,
):

    info = MARKETS[symbol]

    side = signal["side"]

    arrow = (
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

    def check(value):

        if value == side:
            return "✅"

        return "—"

    return (
        "👑 KING OF XAU_NAS\n"
        f"{info['emoji']} "
        f"{symbol} — "
        f"{info['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"

        f"{arrow} "
        f"SIGNAL CONFIRMED — "
        f"{side}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"⚙️ Mode: "
        f"{signal['mode']}\n"

        f"💯 Confidence: "
        f"{signal['confidence']}%\n"

        f"💰 Entry: "
        f"{fmt(symbol, signal['price'])}\n"

        f"🛑 SL: "
        f"{fmt(symbol, signal['sl'])}\n"

        f"🎯 TP1: "
        f"{fmt(symbol, signal['tp1'])}\n"

        f"🎯 TP2: "
        f"{fmt(symbol, signal['tp2'])}\n"

        f"🎯 TP3: "
        f"{fmt(symbol, signal['tp3'])}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"📊 EMA20: "
        f"{fmt(symbol, signal['ema20'])}\n"

        f"📊 EMA50: "
        f"{fmt(symbol, signal['ema50'])}\n"

        f"📈 RSI14: "
        f"{signal['rsi']:.1f}\n"

        f"⚡ ATR14: "
        f"{fmt(symbol, signal['atr'])}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"🏗 BOS: "
        f"{check(signal['bos'])}\n"

        f"🔄 CHoCH: "
        f"{check(signal['choch'])}\n"

        f"💧 Liquidity: "
        f"{check(signal['liquidity'])}\n"

        f"📦 FVG: "
        f"{check(signal['fvg'])}\n"

        f"⚡ Momentum: "
        f"{check(signal['momentum'])}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"⏱ Timeframe: "
        f"{TIMEFRAME}\n"

        f"🕐 {timestamp}\n\n"

        "⚠️ Analysis only — "
        "not financial advice."
    )


# ============================================================
# ANALYZE MARKET
# ============================================================

async def analyze_market(
    application,
    symbol,
    mode,
    send_signal=True,
):

    try:

        df = fetch_market_data(
            symbol
        )

        df = add_indicators(
            df
        )

        signal, confidence, reason = (
            calculate_signal(
                df,
                mode,
            )
        )

        last = df.iloc[-1]

        price = float(
            last["close"]
        )

        logger.info(
            "%s → %s | "
            "Price=%s | RSI=%.1f",
            symbol,
            reason,
            fmt(
                symbol,
                price,
            ),
            float(
                last["rsi"]
            ),
        )

        if not signal:

            LATEST_RESULTS[symbol] = {
                "emoji": MARKETS[
                    symbol
                ]["emoji"],
                "text": reason,
            }

            return None

        candle_time = str(
            last["datetime"]
        )

        signal_key = (
            f"{mode}:"
            f"{symbol}:"
            f"{candle_time}:"
            f"{signal['side']}"
        )

        LATEST_RESULTS[symbol] = {
            "emoji": MARKETS[
                symbol
            ]["emoji"],
            "text": (
                f"{signal['side']} "
                f"{confidence}%"
            ),
        }

        # Prevent duplicate Telegram alerts.

        if (
            LAST_SIGNALS.get(symbol)
            ==
            signal_key
        ):

            logger.info(
                "%s → duplicate signal skipped",
                symbol,
            )

            return signal

        LAST_SIGNALS[symbol] = (
            signal_key
        )

        if send_signal:

            message = (
                build_signal_message(
                    symbol,
                    signal,
                )
            )

            sent = await send_telegram(
                application,
                message,
            )

            if sent:

                logger.info(
                    "%s → %s SIGNAL SENT "
                    "%s%%",
                    symbol,
                    signal["side"],
                    confidence,
                )

        return signal

    except Exception as error:

        logger.warning(
            "%s → DATA/SCAN ERROR: %s",
            symbol,
            error,
        )

        LATEST_RESULTS[symbol] = {
            "emoji": MARKETS[
                symbol
            ]["emoji"],
            "text": (
                f"ERROR: {error}"
            ),
        }

        return None


# ============================================================
# MANUAL SCAN
# ============================================================

async def manual_scan(
    application,
    mode,
):

    logger.info(
        "=============================================="
    )

    logger.info(
        "MANUAL %s SCAN STARTED",
        mode,
    )

    found = 0

    for symbol in MARKETS:

        signal = await analyze_market(
            application,
            symbol,
            mode,
            send_signal=True,
        )

        if signal:
            found += 1

        await asyncio.sleep(1)

    logger.info(
        "%s scan finished. "
        "Signals: %s",
        mode,
        found,
    )


# ============================================================
# AUTOMATIC SCANNER
# ============================================================

async def scanner_loop(
    application,
):

    global SCANNER_RUNNING

    SCANNER_RUNNING = True

    logger.info(
        "=============================================="
    )

    logger.info(
        "👑 AUTOMATIC SCANNER STARTED"
    )

    logger.info(
        "Mode: %s",
        MODE,
    )

    logger.info(
        "Markets: %s",
        ", ".join(
            MARKETS.keys()
        ),
    )

    logger.info(
        "=============================================="
    )

    while True:

        try:

            current_mode = MODE

            await manual_scan(
                application,
                current_mode,
            )

        except Exception as error:

            logger.error(
                "Scanner error: %s",
                error,
            )

        logger.info(
            "Waiting %s seconds...",
            SCAN_SECONDS,
        )

        await asyncio.sleep(
            SCAN_SECONDS
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
        "Background scanner task created."
    )


# ============================================================
# VALIDATION
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
            "Missing environment variable(s): "
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
        "👑 KING OF XAU_NAS"
    )

    logger.info(
        "Starting FULL Telegram bot..."
    )

    logger.info(
        "Markets: %s",
        ", ".join(
            MARKETS.keys()
        ),
    )

    logger.info(
        "Timeframe: %s",
        TIMEFRAME,
    )

    logger.info(
        "Normal confidence: %s%%",
        NORMAL_CONFIDENCE,
    )

    logger.info(
        "Scalp confidence: %s%%",
        SCALP_CONFIDENCE,
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

    # Telegram.

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

    # Commands.

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

    application.add_handler(
        CommandHandler(
            "scan",
            scan_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "scalp",
            scalp_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "normal",
            normal_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "signals",
            signals_command,
        )
    )

    # Error handler.

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
# START
# ============================================================

if __name__ == "__main__":

    main()
