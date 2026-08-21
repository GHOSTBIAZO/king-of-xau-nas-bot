import os
import json
import time
import asyncio
import logging
from threading import Thread, Lock
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
# 👑 KING OF XAU_NAS
# 4-MARKET RATE-LIMIT-SAFE TELEGRAM SCANNER
# ============================================================

BOT_NAME = "👑 KING OF XAU_NAS"

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

TIMEFRAME = os.getenv(
    "INTERVAL",
    "15min"
)

OUTPUT_SIZE = int(
    os.getenv("OUTPUT_SIZE", "80")
)

# ============================================================
# RATE LIMIT PROTECTION
# ============================================================

# Full refresh every 5 minutes.
AUTO_SCAN_SECONDS = int(
    os.getenv(
        "AUTO_SCAN_SECONDS",
        "300"
    )
)

# Minimum gap between API requests.
REQUEST_GAP_SECONDS = float(
    os.getenv(
        "REQUEST_GAP_SECONDS",
        "8"
    )
)

# Pause after HTTP 429.
RATE_LIMIT_COOLDOWN_SECONDS = int(
    os.getenv(
        "RATE_LIMIT_COOLDOWN_SECONDS",
        "180"
    )
)

# Cache is considered fresh for this period.
CACHE_SECONDS = int(
    os.getenv(
        "CACHE_SECONDS",
        "300"
    )
)

# ============================================================
# SIGNAL SETTINGS
# ============================================================

NORMAL_CONFIDENCE = int(
    os.getenv(
        "NORMAL_CONFIDENCE",
        "70"
    )
)

SCALP_CONFIDENCE = int(
    os.getenv(
        "SCALP_CONFIDENCE",
        "60"
    )
)

# ============================================================
# FILES
# ============================================================

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

SCANNER_RUNNING = False

LAST_API_REQUEST = 0.0

RATE_LIMIT_UNTIL = 0.0

API_LOCK = Lock()

DATA_CACHE = {}

LATEST_RESULTS = {}

LAST_SIGNALS = {}

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    "KING_OF_XAU_NAS"
)

# ============================================================
# FLASK / RENDER HEALTH SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():

    return "KING OF XAU_NAS ONLINE"


@app.route("/health")
def health():

    cooldown = max(
        0,
        int(
            RATE_LIMIT_UNTIL -
            time.time()
        ),
    )

    return {
        "status": "online",
        "bot": BOT_NAME,
        "mode": MODE,
        "scanner": SCANNER_RUNNING,
        "markets": list(
            MARKETS.keys()
        ),
        "cached_markets": len(
            DATA_CACHE
        ),
        "cooldown_seconds": cooldown,
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

        if os.path.exists(
            CHAT_ID_FILE
        ):

            with open(
                CHAT_ID_FILE,
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(
                    file
                )

                return data.get(
                    "chat_id"
                )

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
                    "chat_id": str(
                        chat_id
                    )
                },
                file,
            )

        logger.info(
            "Telegram Chat ID saved."
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

    target = (
        chat_id
        or CHAT_ID
    )

    if not target:

        logger.warning(
            "No TELEGRAM_CHAT_ID. "
            "Send /start first."
        )

        return False

    try:

        # Plain text intentionally.
        # This prevents Telegram:
        # "can't parse entities"
        # errors.

        await application.bot.send_message(
            chat_id=target,
            text=message,
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

    if not update.message:
        return

    if not update.effective_chat:
        return

    CHAT_ID = str(
        update.effective_chat.id
    )

    save_chat_id(
        CHAT_ID
    )

    message = (
        "👑 KING OF XAU_NAS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 BOT ONLINE\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "📊 ACTIVE MARKETS\n"
        "🟡 XAU/USD — Gold\n"
        "🇬🇧 GBP/USD\n"
        "💷 GBP/JPY\n"
        "🇪🇺 EUR/USD\n\n"

        f"⚙️ Mode: {MODE}\n"
        f"⏱ Timeframe: {TIMEFRAME}\n\n"

        "COMMANDS\n"
        "/status\n"
        "/watchlist\n"
        "/scan\n"
        "/scalp\n"
        "/normal\n"
        "/signals\n\n"

        "🛡 Rate-limit protection ACTIVE\n"
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

    cooldown = max(
        0,
        int(
            RATE_LIMIT_UNTIL -
            time.time()
        ),
    )

    cache_lines = []

    for symbol in MARKETS:

        cached = DATA_CACHE.get(
            symbol
        )

        if cached:

            age = int(
                time.time()
                -
                cached["timestamp"]
            )

            cache_lines.append(
                f"💾 {symbol}: "
                f"{age}s old"
            )

        else:

            cache_lines.append(
                f"⏳ {symbol}: "
                "no data"
            )

    message = (
        "👑 KING OF XAU_NAS — STATUS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "🟢 Bot: ONLINE\n"
        "🟢 Telegram: CONNECTED\n"
        "🟢 Scanner: RUNNING\n"
        "🟢 Signal engine: ACTIVE\n\n"

        f"⚙️ Mode: {MODE}\n"
        f"⏱ Timeframe: {TIMEFRAME}\n"
        f"📊 Markets: {len(MARKETS)}\n\n"

        "CACHE\n"
        + "\n".join(
            cache_lines
        )
        + "\n\n"

        f"⏳ API cooldown: "
        f"{cooldown}s\n"

        f"🔄 Refresh: every "
        f"{AUTO_SCAN_SECONDS}s\n"

        f"🛡 Request gap: "
        f"{REQUEST_GAP_SECONDS}s\n\n"

        "Rate-limit protection: ACTIVE"
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

        if symbol in DATA_CACHE:

            status = "💾 DATA READY"

        else:

            status = "⏳ WAITING"

        lines.append(
            f"{info['emoji']} "
            f"{symbol}\n"
            f"   {info['name']} — "
            f"{status}"
        )

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━━━",
            f"⚙️ Mode: {MODE}",
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
        f"🎯 Minimum confidence: "
        f"{NORMAL_CONFIDENCE}%\n"
        f"⏱ Timeframe: {TIMEFRAME}\n\n"
        "The next scan will use "
        "the protected market cache."
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
        f"🎯 Minimum confidence: "
        f"{SCALP_CONFIDENCE}%\n"
        f"⏱ Timeframe: {TIMEFRAME}\n\n"
        "Using cached market data "
        "where available.\n"
        "🛡 Rate-limit protection ACTIVE."
    )

    asyncio.create_task(
        cached_scan(
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

    if not update.message:
        return

    await update.message.reply_text(
        "🔎 KING OF XAU_NAS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📡 SCAN STARTED\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Checking the four markets.\n"
        "Rate-limit protection ACTIVE."
    )

    asyncio.create_task(
        controlled_manual_scan(
            context.application,
            MODE,
        )
    )


# ============================================================
# MANUAL SCAN
# ============================================================

async def controlled_manual_scan(
    application,
    mode,
):

    # First analyze existing cache.

    await analyze_cached_markets(
        application,
        mode,
    )

    # Only refresh markets that are missing
    # or whose cache is older than CACHE_SECONDS.

    for symbol in MARKETS:

        cached = DATA_CACHE.get(
            symbol
        )

        needs_refresh = (
            cached is None
            or
            (
                time.time()
                -
                cached["timestamp"]
                >
                CACHE_SECONDS
            )
        )

        if not needs_refresh:

            continue

        if time.time() < RATE_LIMIT_UNTIL:

            logger.warning(
                "API cooldown active. "
                "Manual refresh stopped."
            )

            break

        try:

            await asyncio.to_thread(
                fetch_market_data,
                symbol,
            )

        except Exception as error:

            logger.warning(
                "%s manual refresh failed: %s",
                symbol,
                error,
            )

            if (
                time.time()
                <
                RATE_LIMIT_UNTIL
            ):

                break

        await asyncio.sleep(
            REQUEST_GAP_SECONDS
        )

    # Analyze whatever data we now have.

    await analyze_cached_markets(
        application,
        mode,
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
            "No scan results yet.\n\n"
            "Use /scan."
        )

        return

    lines = [
        "👑 KING OF XAU_NAS — SIGNAL BOARD",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for symbol in MARKETS:

        result = LATEST_RESULTS.get(
            symbol
        )

        if result:

            lines.append(
                f"{result['emoji']} "
                f"{symbol}: "
                f"{result['text']}"
            )

        else:

            lines.append(
                f"{MARKETS[symbol]['emoji']} "
                f"{symbol}: WAITING"
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
        "Telegram exception: %s",
        context.error,
    )


# ============================================================
# API SLOT
# ============================================================

def wait_for_api_slot():

    global LAST_API_REQUEST

    now = time.time()

    if now < RATE_LIMIT_UNTIL:

        return False

    elapsed = (
        now -
        LAST_API_REQUEST
    )

    if (
        elapsed <
        REQUEST_GAP_SECONDS
    ):

        time.sleep(
            REQUEST_GAP_SECONDS -
            elapsed
        )

    LAST_API_REQUEST = time.time()

    return True


# ============================================================
# FETCH TWELVE DATA
# ============================================================

def fetch_market_data(
    symbol,
):

    global RATE_LIMIT_UNTIL

    if not TWELVE_DATA_API_KEY:

        raise RuntimeError(
            "TWELVE_DATA_API_KEY "
            "is missing."
        )

    with API_LOCK:

        if not wait_for_api_slot():

            raise RuntimeError(
                "API cooldown active."
            )

        logger.info(
            "📡 Twelve Data request → %s",
            symbol,
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

        # ----------------------------------------------------
        # 429
        # ----------------------------------------------------

        if response.status_code == 429:

            RATE_LIMIT_UNTIL = (
                time.time()
                +
                RATE_LIMIT_COOLDOWN_SECONDS
            )

            logger.warning(
                "🚨 HTTP 429 from Twelve Data."
            )

            logger.warning(
                "Pausing API requests for %s seconds.",
                RATE_LIMIT_COOLDOWN_SECONDS,
            )

            raise RuntimeError(
                "Twelve Data rate limit."
            )

        response.raise_for_status()

        data = response.json()

        # Twelve Data can return an error
        # inside a successful HTTP response.

        if "status" in data:

            if str(
                data.get("status")
            ).lower() == "error":

                message = data.get(
                    "message",
                    "Twelve Data error.",
                )

                raise RuntimeError(
                    message
                )

        if "values" not in data:

            message = data.get(
                "message",
                "No values returned.",
            )

            raise RuntimeError(
                message
            )

        df = pd.DataFrame(
            data["values"]
        )

        required_columns = [
            "datetime",
            "open",
            "high",
            "low",
            "close",
        ]

        for column in required_columns:

            if column not in df.columns:

                raise RuntimeError(
                    f"{symbol}: missing "
                    f"{column}"
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
                f"{symbol}: only "
                f"{len(df)} candles."
            )

        DATA_CACHE[
            symbol
        ] = {
            "data": df,
            "timestamp": time.time(),
        }

        logger.info(
            "💾 %s cached successfully.",
            symbol,
        )

        return df


# ============================================================
# CACHE GETTER
# ============================================================

def get_cached_data(
    symbol,
):

    cached = DATA_CACHE.get(
        symbol
    )

    if not cached:

        return None

    return cached["data"]


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


# ============================================================
# CHOCH
# ============================================================

def detect_choch(df):

    if len(df) < 10:

        return None

    previous = df.iloc[-8:-1]

    last = df.iloc[-1]

    if (
        last["close"]
        >
        previous["high"].max()
    ):

        return "BUY"

    if (
        last["close"]
        <
        previous["low"].min()
    ):

        return "SELL"

    return None


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def detect_liquidity(df):

    if len(df) < 20:

        return None

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


# ============================================================
# FVG
# ============================================================

def detect_fvg(df):

    if len(df) < 5:

        return None

    first = df.iloc[-3]

    middle = df.iloc[-2]

    last = df.iloc[-1]

    if (
        last["low"] > first["high"]
        and
        middle["close"]
        >
        middle["open"]
    ):

        return "BUY"

    if (
        last["high"] < first["low"]
        and
        middle["close"]
        <
        middle["open"]
    ):

        return "SELL"

    return None


# ============================================================
# MOMENTUM
# ============================================================

def detect_momentum(df):

    if len(df) < 3:

        return None

    last = df.iloc[-1]

    previous = df.iloc[-2]

    if (
        last["close"]
        >
        previous["close"]
    ):

        return "BUY"

    if (
        last["close"]
        <
        previous["close"]
    ):

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

    if atr <= 0:

        return (
            None,
            0,
            "Invalid ATR",
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

    if 52 <= rsi <= 70:

        buy += 15

    elif 30 <= rsi <= 48:

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
    # SELECT SIDE
    # --------------------------------------------------------

    if buy >= sell:

        side = "BUY"

        confidence = buy

    else:

        side = "SELL"

        confidence = sell

    if mode == "SCALP":

        threshold = SCALP_CONFIDENCE

    else:

        threshold = NORMAL_CONFIDENCE

    if confidence < threshold:

        return (
            None,
            confidence,
            (
                f"No qualifying {side} "
                f"signal: "
                f"{confidence}%/"
                f"{threshold}%"
            ),
        )

    # --------------------------------------------------------
    # TARGETS
    # --------------------------------------------------------

    if mode == "SCALP":

        sl_mult = 1.0

        tp1_mult = 1.2

        tp2_mult = 1.8

        tp3_mult = 2.5

    else:

        sl_mult = 1.5

        tp1_mult = 2.0

        tp2_mult = 3.0

        tp3_mult = 5.0

    if side == "BUY":

        sl = (
            price -
            atr * sl_mult
        )

        tp1 = (
            price +
            atr * tp1_mult
        )

        tp2 = (
            price +
            atr * tp2_mult
        )

        tp3 = (
            price +
            atr * tp3_mult
        )

    else:

        sl = (
            price +
            atr * sl_mult
        )

        tp1 = (
            price -
            atr * tp1_mult
        )

        tp2 = (
            price -
            atr * tp2_mult
        )

        tp3 = (
            price -
            atr * tp3_mult
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
# BUILD SIGNAL MESSAGE
# ============================================================

def build_signal_message(
    symbol,
    signal,
):

    info = MARKETS[
        symbol
    ]

    side = signal[
        "side"
    ]

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

        if value == side:

            return "✅"

        return "—"

    return (
        "👑 KING OF XAU_NAS\n"
        f"{info['emoji']} "
        f"{symbol} — "
        f"{info['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"

        f"{direction} "
        f"SIGNAL CONFIRMED — "
        f"{side}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"⚙️ Mode: "
        f"{signal['mode']}\n"

        f"💯 Confidence: "
        f"{signal['confidence']}%\n"

        f"💰 Entry: "
        f"{fmt(symbol, signal['price'])}\n"

        f"🛑 Stop Loss: "
        f"{fmt(symbol, signal['sl'])}\n"

        f"🎯 Take Profit 1: "
        f"{fmt(symbol, signal['tp1'])}\n"

        f"🎯 Take Profit 2: "
        f"{fmt(symbol, signal['tp2'])}\n"

        f"🎯 Take Profit 3: "
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
        f"{mark(signal['bos'])}\n"

        f"🔄 CHoCH: "
        f"{mark(signal['choch'])}\n"

        f"💧 Liquidity: "
        f"{mark(signal['liquidity'])}\n"

        f"📦 FVG: "
        f"{mark(signal['fvg'])}\n"

        f"⚡ Momentum: "
        f"{mark(signal['momentum'])}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"⏱ Timeframe: "
        f"{TIMEFRAME}\n"

        f"🕐 {timestamp}\n\n"

        "⚠️ Analysis only — "
        "not financial advice."
    )


# ============================================================
# ANALYZE ONE CACHED MARKET
# ============================================================

async def analyze_market(
    application,
    symbol,
    mode,
):

    try:

        df = get_cached_data(
            symbol
        )

        if df is None:

            LATEST_RESULTS[
                symbol
            ] = {
                "emoji": MARKETS[
                    symbol
                ]["emoji"],
                "text": "WAITING FOR DATA",
            }

            return None

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
            "%s → %s | Price=%s",
            symbol,
            reason,
            fmt(
                symbol,
                price,
            ),
        )

        if signal is None:

            LATEST_RESULTS[
                symbol
            ] = {
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

        LATEST_RESULTS[
            symbol
        ] = {
            "emoji": MARKETS[
                symbol
            ]["emoji"],
            "text": (
                f"{signal['side']} "
                f"{confidence}%"
            ),
        }

        # Don't send the same signal repeatedly.

        if (
            LAST_SIGNALS.get(
                symbol
            )
            ==
            signal_key
        ):

            logger.info(
                "%s → duplicate "
                "signal skipped.",
                symbol,
            )

            return signal

        LAST_SIGNALS[
            symbol
        ] = signal_key

        message = (
            build_signal_message(
                symbol,
                signal,
            )
        )

        await send_telegram(
            application,
            message,
        )

        logger.info(
            "🚨 %s %s SIGNAL SENT",
            symbol,
            signal["side"],
        )

        return signal

    except Exception as error:

        logger.warning(
            "%s analysis error: %s",
            symbol,
            error,
        )

        return None


# ============================================================
# ANALYZE ALL CACHED DATA
# ============================================================

async def analyze_cached_markets(
    application,
    mode,
):

    logger.info(
        "Analyzing cached markets..."
    )

    signals = 0

    for symbol in MARKETS:

        result = await analyze_market(
            application,
            symbol,
            mode,
        )

        if result:

            signals += 1

        await asyncio.sleep(
            0.2
        )

    logger.info(
        "Cached analysis complete. "
        "Signals: %s",
        signals,
    )


# ============================================================
# REFRESH ONLY OLD/MISSING DATA
# ============================================================

async def refresh_markets():

    logger.info(
        "Starting controlled market refresh."
    )

    refreshed = 0

    for symbol in MARKETS:

        # Stop immediately during 429 cooldown.

        if (
            time.time()
            <
            RATE_LIMIT_UNTIL
        ):

            remaining = int(
                RATE_LIMIT_UNTIL -
                time.time()
            )

            logger.warning(
                "429 cooldown active: "
                "%ss",
                remaining,
            )

            break

        cached = DATA_CACHE.get(
            symbol
        )

        # Don't request a market if
        # its cache is still fresh.

        if cached:

            age = (
                time.time()
                -
                cached["timestamp"]
            )

            if age < CACHE_SECONDS:

                logger.info(
                    "%s → cache fresh "
                    "(%ss old)",
                    symbol,
                    int(age),
                )

                continue

        try:

            await asyncio.to_thread(
                fetch_market_data,
                symbol,
            )

            refreshed += 1

        except Exception as error:

            logger.warning(
                "%s refresh failed: %s",
                symbol,
                error,
            )

            if (
                time.time()
                <
                RATE_LIMIT_UNTIL
            ):

                break

        # Mandatory gap.

        await asyncio.sleep(
            REQUEST_GAP_SECONDS
        )

    logger.info(
        "Refresh complete: "
        "%s/%s requested",
        refreshed,
        len(MARKETS),
    )


# ============================================================
# FULL SCAN
# ============================================================

async def full_scan(
    application,
    mode,
):

    # Analyze existing data FIRST.

    await analyze_cached_markets(
        application,
        mode,
    )

    # Then refresh only stale data.

    await refresh_markets()

    # Analyze refreshed data.

    await analyze_cached_markets(
        application,
        mode,
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
        "===================================="
    )

    logger.info(
        "👑 KING OF XAU_NAS SCANNER ONLINE"
    )

    logger.info(
        "Markets: %s",
        ", ".join(
            MARKETS.keys()
        ),
    )

    logger.info(
        "Mode: %s",
        MODE,
    )

    logger.info(
        "Refresh interval: %ss",
        AUTO_SCAN_SECONDS,
    )

    logger.info(
        "Request gap: %ss",
        REQUEST_GAP_SECONDS,
    )

    logger.info(
        "===================================="
    )

    while True:

        start_time = time.time()

        try:

            current_mode = MODE

            await full_scan(
                application,
                current_mode,
            )

        except Exception as error:

            logger.error(
                "Scanner error: %s",
                error,
            )

        elapsed = (
            time.time()
            -
            start_time
        )

        wait_time = max(
            15,
            AUTO_SCAN_SECONDS
            -
            int(elapsed),
        )

        logger.info(
            "Next scan in %ss",
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
# CONFIG
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
            "Missing environment variables: "
            +
            ", ".join(missing)
        )


# ============================================================
# MAIN
# ============================================================

def main():

    validate_config()

    logger.info(
        "===================================="
    )

    logger.info(
        "👑 KING OF XAU_NAS"
    )

    logger.info(
        "4-MARKET VERSION"
    )

    logger.info(
        "===================================="
    )

    logger.info(
        "Active markets: %s",
        ", ".join(
            MARKETS.keys()
        ),
    )

    logger.info(
        "Timeframe: %s",
        TIMEFRAME,
    )

    logger.info(
        "Automatic scan: %ss",
        AUTO_SCAN_SECONDS,
    )

    logger.info(
        "Request gap: %ss",
        REQUEST_GAP_SECONDS,
    )

    logger.info(
        "429 cooldown: %ss",
        RATE_LIMIT_COOLDOWN_SECONDS,
    )

    logger.info(
        "===================================="
    )

    # --------------------------------------------------------
    # WEB SERVER
    # --------------------------------------------------------

    web_thread = Thread(
        target=run_web_server,
        daemon=True,
    )

    web_thread.start()

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------

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

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "🚀 Telegram polling starting..."
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
