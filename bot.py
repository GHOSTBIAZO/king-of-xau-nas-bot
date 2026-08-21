import os
import time
import json
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
# 👑 KING OF XAU_NAS — 4 MARKET VERSION
# XAU/USD | GBP/USD | GBP/JPY | EUR/USD
# ============================================================

BOT_NAME = "👑 KING OF XAU_NAS"

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TWELVE_DATA_API_KEY = os.getenv(
    "TWELVE_DATA_API_KEY", ""
).strip()

PORT = int(os.getenv("PORT", "10000"))

TIMEFRAME = os.getenv(
    "INTERVAL", "15min"
)

OUTPUT_SIZE = int(
    os.getenv("OUTPUT_SIZE", "100")
)

AUTO_SCAN_SECONDS = int(
    os.getenv("AUTO_SCAN_SECONDS", "300")
)

REQUEST_GAP_SECONDS = float(
    os.getenv("REQUEST_GAP_SECONDS", "8")
)

RATE_LIMIT_COOLDOWN_SECONDS = int(
    os.getenv(
        "RATE_LIMIT_COOLDOWN_SECONDS",
        "180"
    )
)

CACHE_SECONDS = int(
    os.getenv("CACHE_SECONDS", "300")
)

NORMAL_CONFIDENCE = int(
    os.getenv("NORMAL_CONFIDENCE", "65")
)

SCALP_CONFIDENCE = int(
    os.getenv("SCALP_CONFIDENCE", "55")
)

CHAT_ID_FILE = "telegram_chat_id.json"

# ============================================================
# MARKETS
# ============================================================

MARKETS = {
    "XAU/USD": {
        "emoji": "🟡",
        "name": "GOLD",
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

DATA_CACHE = {}

LATEST_RESULTS = {}

LAST_SIGNAL_KEYS = {}

LAST_API_REQUEST = 0.0

RATE_LIMIT_UNTIL = 0.0

API_LOCK = Lock()

SCANNER_RUNNING = False

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(
    "KING_OF_XAU_NAS"
)

# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "KING OF XAU_NAS ONLINE"


@app.route("/health")
def health():

    cooldown = max(
        0,
        int(RATE_LIMIT_UNTIL - time.time())
    )

    return {
        "status": "online",
        "mode": MODE,
        "scanner": SCANNER_RUNNING,
        "markets": list(MARKETS.keys()),
        "cached_markets": len(DATA_CACHE),
        "api_cooldown": cooldown,
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
            ) as f:

                data = json.load(f)

                return data.get("chat_id")

    except Exception as e:

        logger.warning(
            "Could not load chat ID: %s",
            e
        )

    return None


def save_chat_id(chat_id):

    try:

        with open(
            CHAT_ID_FILE,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                {"chat_id": str(chat_id)},
                f
            )

    except Exception as e:

        logger.error(
            "Could not save chat ID: %s",
            e
        )


CHAT_ID = load_chat_id()

# ============================================================
# TELEGRAM MESSAGE
# ============================================================

async def send_message(
    application,
    message,
    chat_id=None,
):

    target = chat_id or CHAT_ID

    if not target:

        logger.warning(
            "No Telegram chat ID."
        )

        return False

    try:

        # Plain text deliberately.
        # Prevents Telegram entity parsing errors.

        await application.bot.send_message(
            chat_id=target,
            text=message,
        )

        return True

    except Exception as e:

        logger.error(
            "Telegram send error: %s",
            e
        )

        return False


# ============================================================
# START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    global CHAT_ID

    if not update.message:
        return

    if update.effective_chat:

        CHAT_ID = str(
            update.effective_chat.id
        )

        save_chat_id(CHAT_ID)

    message = (
        "👑 KING OF XAU_NAS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 BOT ONLINE\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "📊 ACTIVE MARKETS\n"
        "🟡 XAU/USD — GOLD\n"
        "🇬🇧 GBP/USD\n"
        "💷 GBP/JPY\n"
        "🇪🇺 EUR/USD\n\n"

        f"⚙️ MODE: {MODE}\n"
        f"⏱ TIMEFRAME: {TIMEFRAME}\n\n"

        "COMMANDS\n"
        "/status\n"
        "/watchlist\n"
        "/scan\n"
        "/scalp\n"
        "/normal\n"
        "/signals\n\n"

        "🛡 Rate-limit protection ACTIVE"
    )

    await update.message.reply_text(
        message
    )


# ============================================================
# STATUS
# ============================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    cooldown = max(
        0,
        int(RATE_LIMIT_UNTIL - time.time())
    )

    lines = [
        "👑 KING OF XAU_NAS — STATUS",
        "━━━━━━━━━━━━━━━━━━━━",
        "🟢 BOT: ONLINE",
        "🟢 SCANNER: ACTIVE",
        "🟢 SIGNAL ENGINE: ACTIVE",
        f"⚙️ MODE: {MODE}",
        f"⏱ TIMEFRAME: {TIMEFRAME}",
        "",
        "CACHE:",
    ]

    for symbol in MARKETS:

        cache = DATA_CACHE.get(symbol)

        if cache:

            age = int(
                time.time() -
                cache["timestamp"]
            )

            lines.append(
                f"💾 {symbol}: {age}s old"
            )

        else:

            lines.append(
                f"⏳ {symbol}: NO DATA"
            )

    lines.extend([
        "",
        f"⏳ API COOLDOWN: {cooldown}s",
        f"🔄 AUTO SCAN: {AUTO_SCAN_SECONDS}s",
        f"🛡 REQUEST GAP: {REQUEST_GAP_SECONDS}s",
    ])

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# WATCHLIST
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

            state = "🟢 READY"

        else:

            state = "⏳ WAITING"

        lines.append(
            f"{info['emoji']} {symbol} — {state}"
        )

    lines.extend([
        "",
        f"⚙️ Mode: {MODE}",
        f"⏱ Timeframe: {TIMEFRAME}",
    ])

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# NORMAL
# ============================================================

async def normal_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    global MODE

    MODE = "NORMAL"

    if update.message:

        await update.message.reply_text(
            "👑 KING OF XAU_NAS\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 NORMAL MODE ACTIVATED\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Minimum confidence: "
            f"{NORMAL_CONFIDENCE}%\n"
            f"⏱ Timeframe: {TIMEFRAME}"
        )


# ============================================================
# SCALP
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
        "⚡ SCALP MODE ACTIVATED\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Minimum confidence: "
        f"{SCALP_CONFIDENCE}%\n"
        f"⏱ Timeframe: {TIMEFRAME}\n\n"
        "Scanning cached market data..."
    )

    asyncio.create_task(
        run_scan(
            context.application,
            "SCALP"
        )
    )


# ============================================================
# SCAN
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
        "🟡 XAU/USD\n"
        "🇬🇧 GBP/USD\n"
        "💷 GBP/JPY\n"
        "🇪🇺 EUR/USD\n\n"
        "🛡 Rate-limit protection ACTIVE."
    )

    asyncio.create_task(
        run_scan(
            context.application,
            MODE
        )
    )


# ============================================================
# SIGNALS
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

    for symbol in MARKETS:

        result = LATEST_RESULTS.get(
            symbol
        )

        if not result:
            continue

        await update.message.reply_text(
            build_result_message(
                symbol,
                result
            )
        )

# ============================================================
# API RATE LIMIT
# ============================================================

def api_slot_available():

    global LAST_API_REQUEST

    if time.time() < RATE_LIMIT_UNTIL:

        return False

    elapsed = (
        time.time() -
        LAST_API_REQUEST
    )

    if elapsed < REQUEST_GAP_SECONDS:

        time.sleep(
            REQUEST_GAP_SECONDS -
            elapsed
        )

    LAST_API_REQUEST = time.time()

    return True


# ============================================================
# FETCH DATA
# ============================================================

def fetch_market_data(symbol):

    global RATE_LIMIT_UNTIL

    if not TWELVE_DATA_API_KEY:

        raise RuntimeError(
            "TWELVE_DATA_API_KEY missing."
        )

    with API_LOCK:

        if not api_slot_available():

            raise RuntimeError(
                "API cooldown active."
            )

        logger.info(
            "Requesting %s",
            symbol
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

        if response.status_code == 429:

            RATE_LIMIT_UNTIL = (
                time.time()
                +
                RATE_LIMIT_COOLDOWN_SECONDS
            )

            raise RuntimeError(
                "Twelve Data HTTP 429."
            )

        response.raise_for_status()

        data = response.json()

        if data.get("status") == "error":

            raise RuntimeError(
                data.get(
                    "message",
                    "Twelve Data error"
                )
            )

        values = data.get("values")

        if not values:

            raise RuntimeError(
                f"No market data for {symbol}"
            )

        df = pd.DataFrame(values)

        required = [
            "datetime",
            "open",
            "high",
            "low",
            "close",
        ]

        for col in required:

            if col not in df.columns:

                raise RuntimeError(
                    f"{symbol}: missing {col}"
                )

        for col in [
            "open",
            "high",
            "low",
            "close",
        ]:

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
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
            df.iloc[::-1]
            .reset_index(drop=True)
        )

        if len(df) < 60:

            raise RuntimeError(
                f"{symbol}: insufficient candles."
            )

        DATA_CACHE[symbol] = {
            "data": df,
            "timestamp": time.time(),
        }

        logger.info(
            "Cached %s",
            symbol
        )

        return df


# ============================================================
# INDICATORS
# ============================================================

def add_indicators(df):

    df = df.copy()

    # EMA

    df["ema20"] = (
        df["close"]
        .ewm(
            span=20,
            adjust=False
        )
        .mean()
    )

    df["ema50"] = (
        df["close"]
        .ewm(
            span=50,
            adjust=False
        )
        .mean()
    )

    # RSI

    delta = df["close"].diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = (
        gain.ewm(
            alpha=1 / 14,
            adjust=False
        ).mean()
    )

    avg_loss = (
        loss.ewm(
            alpha=1 / 14,
            adjust=False
        ).mean()
    )

    rs = avg_gain / avg_loss.replace(
        0,
        float("nan")
    )

    df["rsi"] = (
        100 -
        (
            100 /
            (1 + rs)
        )
    )

    df["rsi"] = df["rsi"].fillna(50)

    # ATR

    previous_close = (
        df["close"].shift(1)
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
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    df["atr"] = (
        true_range
        .ewm(
            alpha=1 / 14,
            adjust=False
        )
        .mean()
    )

    return df


# ============================================================
# MARKET STRUCTURE
# ============================================================

def structure_signal(df):

    last = df.iloc[-1]

    previous = df.iloc[-6:-1]

    buy = False
    sell = False

    # Break of structure

    if last["close"] > previous["high"].max():

        buy = True

    if last["close"] < previous["low"].min():

        sell = True

    if buy and not sell:
        return "BUY"

    if sell and not buy:
        return "SELL"

    return None


def liquidity_signal(df):

    last = df.iloc[-1]

    previous = df.iloc[-16:-1]

    previous_high = previous["high"].max()

    previous_low = previous["low"].min()

    # Bearish sweep

    if (
        last["high"] > previous_high
        and
        last["close"] < previous_high
    ):

        return "SELL"

    # Bullish sweep

    if (
        last["low"] < previous_low
        and
        last["close"] > previous_low
    ):

        return "BUY"

    return None


def fvg_signal(df):

    if len(df) < 5:
        return None

    a = df.iloc[-3]
    b = df.iloc[-2]
    c = df.iloc[-1]

    # Bullish FVG

    if (
        c["low"] > a["high"]
        and
        b["close"] > b["open"]
    ):

        return "BUY"

    # Bearish FVG

    if (
        c["high"] < a["low"]
        and
        b["close"] < b["open"]
    ):

        return "SELL"

    return None


def momentum_signal(df):

    last = df.iloc[-1]

    previous = df.iloc[-2]

    if last["close"] > previous["close"]:
        return "BUY"

    if last["close"] < previous["close"]:
        return "SELL"

    return None


# ============================================================
# BALANCED SIGNAL ENGINE
# ============================================================

def calculate_signal(
    df,
    mode,
):

    last = df.iloc[-1]

    price = float(last["close"])

    ema20 = float(last["ema20"])

    ema50 = float(last["ema50"])

    rsi = float(last["rsi"])

    atr = float(last["atr"])

    if atr <= 0:
        return None

    buy_score = 0
    sell_score = 0

    reasons_buy = []
    reasons_sell = []

    # --------------------------------------------------------
    # EMA TREND
    # --------------------------------------------------------

    if ema20 > ema50:

        buy_score += 20
        reasons_buy.append("EMA trend")

    elif ema20 < ema50:

        sell_score += 20
        reasons_sell.append("EMA trend")

    # --------------------------------------------------------
    # PRICE VS EMA20
    # --------------------------------------------------------

    if price > ema20:

        buy_score += 10
        reasons_buy.append("Price above EMA20")

    elif price < ema20:

        sell_score += 10
        reasons_sell.append("Price below EMA20")

    # --------------------------------------------------------
    # RSI
    # Balanced BUY and SELL conditions
    # --------------------------------------------------------

    if 52 <= rsi <= 68:

        buy_score += 15
        reasons_buy.append("Bullish RSI")

    elif 32 <= rsi <= 48:

        sell_score += 15
        reasons_sell.append("Bearish RSI")

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    structure = structure_signal(df)

    if structure == "BUY":

        buy_score += 20
        reasons_buy.append("BOS BUY")

    elif structure == "SELL":

        sell_score += 20
        reasons_sell.append("BOS SELL")

    # --------------------------------------------------------
    # LIQUIDITY
    # --------------------------------------------------------

    liquidity = liquidity_signal(df)

    if liquidity == "BUY":

        buy_score += 10
        reasons_buy.append("Bullish liquidity")

    elif liquidity == "SELL":

        sell_score += 10
        reasons_sell.append("Bearish liquidity")

    # --------------------------------------------------------
    # FVG
    # --------------------------------------------------------

    fvg = fvg_signal(df)

    if fvg == "BUY":

        buy_score += 10
        reasons_buy.append("Bullish FVG")

    elif fvg == "SELL":

        sell_score += 10
        reasons_sell.append("Bearish FVG")

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    momentum = momentum_signal(df)

    if momentum == "BUY":

        buy_score += 10
        reasons_buy.append("Bullish momentum")

    elif momentum == "SELL":

        sell_score += 10
        reasons_sell.append("Bearish momentum")

    # --------------------------------------------------------
    # CHOOSE SIDE
    # --------------------------------------------------------

    if buy_score > sell_score:

        side = "BUY"
        score = buy_score
        reasons = reasons_buy

    elif sell_score > buy_score:

        side = "SELL"
        score = sell_score
        reasons = reasons_sell

    else:

        return None

    # --------------------------------------------------------
    # CONFIDENCE
    # --------------------------------------------------------

    # Prevents a weak side winning just because
    # the other side is also weak.

    if mode == "SCALP":

        threshold = SCALP_CONFIDENCE

    else:

        threshold = NORMAL_CONFIDENCE

    if score < threshold:

        return None

    # --------------------------------------------------------
    # ATR TARGETS
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
        tp3_multiplier = 4.5

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

    return {
        "side": side,
        "confidence": score,
        "entry": price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "structure": structure,
        "liquidity": liquidity,
        "fvg": fvg,
        "momentum": momentum,
        "reasons": reasons,
        "mode": mode,
        "candle": str(last["datetime"]),
    }


# ============================================================
# FORMAT PRICE
# ============================================================

def price_fmt(
    symbol,
    value,
):

    digits = MARKETS[
        symbol
    ]["digits"]

    return f"{value:,.{digits}f}"


# ============================================================
# FULL SIGNAL MESSAGE
# ============================================================

def build_signal_message(
    symbol,
    signal,
):

    info = MARKETS[symbol]

    side = signal["side"]

    if side == "BUY":

        direction = "🟢 BUY"

    else:

        direction = "🔴 SELL"

    reasons = ", ".join(
        signal["reasons"]
    )

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    return (
        "👑 KING OF XAU_NAS\n"
        f"{info['emoji']} {symbol} — "
        f"{info['name']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🚨 SIGNAL CONFIRMED — {direction}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"⚙️ Mode: {signal['mode']}\n"
        f"💯 Confidence: {signal['confidence']}%\n"
        f"⏱ Timeframe: {TIMEFRAME}\n\n"

        f"💰 ENTRY: "
        f"{price_fmt(symbol, signal['entry'])}\n"

        f"🛑 STOP LOSS: "
        f"{price_fmt(symbol, signal['sl'])}\n"

        f"🎯 TAKE PROFIT 1: "
        f"{price_fmt(symbol, signal['tp1'])}\n"

        f"🎯 TAKE PROFIT 2: "
        f"{price_fmt(symbol, signal['tp2'])}\n"

        f"🎯 TAKE PROFIT 3: "
        f"{price_fmt(symbol, signal['tp3'])}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"📊 EMA20: "
        f"{price_fmt(symbol, signal['ema20'])}\n"

        f"📊 EMA50: "
        f"{price_fmt(symbol, signal['ema50'])}\n"

        f"📈 RSI14: "
        f"{signal['rsi']:.1f}\n"

        f"⚡ ATR14: "
        f"{price_fmt(symbol, signal['atr'])}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"🏗 BOS: "
        f"{signal['structure'] or 'NONE'}\n"

        f"💧 Liquidity: "
        f"{signal['liquidity'] or 'NONE'}\n"

        f"📦 FVG: "
        f"{signal['fvg'] or 'NONE'}\n"

        f"⚡ Momentum: "
        f"{signal['momentum'] or 'NONE'}\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"🧠 Reasons: {reasons}\n"
        f"🕐 {now}\n\n"

        "⚠️ Analysis only — "
        "not financial advice."
    )


# ============================================================
# RESULT MESSAGE
# ============================================================

def build_result_message(
    symbol,
    result,
):

    info = MARKETS[symbol]

    if result.get("signal"):

        return build_signal_message(
            symbol,
            result["signal"]
        )

    return (
        "👑 KING OF XAU_NAS\n"
        f"{info['emoji']} {symbol}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ NO QUALIFYING SIGNAL\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 Price: "
        f"{price_fmt(symbol, result['price'])}\n"
        f"📊 EMA20: "
        f"{price_fmt(symbol, result['ema20'])}\n"
        f"📊 EMA50: "
        f"{price_fmt(symbol, result['ema50'])}\n"
        f"📈 RSI: {result['rsi']:.1f}\n"
        f"⚡ ATR: "
        f"{price_fmt(symbol, result['atr'])}\n\n"
        "Waiting for a stronger setup."
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

        cached = DATA_CACHE.get(
            symbol
        )

        if not cached:

            return None

        df = add_indicators(
            cached["data"]
        )

        last = df.iloc[-1]

        signal = calculate_signal(
            df,
            mode
        )

        # ----------------------------------------------------
        # Store result even when there is no signal.
        # ----------------------------------------------------

        base_result = {
            "signal": signal,
            "price": float(last["close"]),
            "ema20": float(last["ema20"]),
            "ema50": float(last["ema50"]),
            "rsi": float(last["rsi"]),
            "atr": float(last["atr"]),
            "timestamp": time.time(),
        }

        LATEST_RESULTS[symbol] = base_result

        if not signal:

            logger.info(
                "%s → NO QUALIFYING SIGNAL",
                symbol
            )

            return None

        # ----------------------------------------------------
        # Prevent duplicate candle signals.
        # ----------------------------------------------------

        signal_key = (
            f"{symbol}|"
            f"{mode}|"
            f"{signal['side']}|"
            f"{signal['candle']}"
        )

        if (
            LAST_SIGNAL_KEYS.get(symbol)
            ==
            signal_key
        ):

            logger.info(
                "%s → duplicate skipped",
                symbol
            )

            return signal

        LAST_SIGNAL_KEYS[symbol] = (
            signal_key
        )

        logger.info(
            "%s → %s %s%%",
            symbol,
            signal["side"],
            signal["confidence"]
        )

        if send_signal:

            await send_message(
                application,
                build_signal_message(
                    symbol,
                    signal
                )
            )

        return signal

    except Exception as e:

        logger.error(
            "%s analysis error: %s",
            symbol,
            e
        )

        return None


# ============================================================
# REFRESH MARKET DATA
# ============================================================

async def refresh_markets():

    refreshed = 0

    for symbol in MARKETS:

        if time.time() < RATE_LIMIT_UNTIL:

            logger.warning(
                "429 cooldown active."
            )

            break

        cached = DATA_CACHE.get(
            symbol
        )

        if cached:

            age = (
                time.time()
                -
                cached["timestamp"]
            )

            if age < CACHE_SECONDS:

                logger.info(
                    "%s cache still fresh.",
                    symbol
                )

                continue

        try:

            await asyncio.to_thread(
                fetch_market_data,
                symbol
            )

            refreshed += 1

        except Exception as e:

            logger.warning(
                "%s refresh failed: %s",
                symbol,
                e
            )

            if time.time() < RATE_LIMIT_UNTIL:

                break

        await asyncio.sleep(
            REQUEST_GAP_SECONDS
        )

    return refreshed


# ============================================================
# FULL SCAN
# ============================================================

async def run_scan(
    application,
    mode,
):

    logger.info(
        "Starting %s scan.",
        mode
    )

    # Analyze cache first.

    for symbol in MARKETS:

        await analyze_market(
            application,
            symbol,
            mode,
            send_signal=True
        )

        await asyncio.sleep(0.2)

    # Refresh stale data.

    await refresh_markets()

    # Analyze fresh data.

    for symbol in MARKETS:

        await analyze_market(
            application,
            symbol,
            mode,
            send_signal=True
        )

        await asyncio.sleep(0.2)

    logger.info(
        "%s scan complete.",
        mode
    )


# ============================================================
# BACKGROUND SCANNER
# ============================================================

async def scanner_loop(
    application,
):

    global SCANNER_RUNNING

    SCANNER_RUNNING = True

    while True:

        try:

            await run_scan(
                application,
                MODE
            )

        except Exception as e:

            logger.error(
                "Scanner error: %s",
                e
            )

        await asyncio.sleep(
            AUTO_SCAN_SECONDS
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


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context,
):

    logger.error(
        "Telegram error: %s",
        context.error
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
            "Missing: "
            + ", ".join(missing)
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
        "👑 KING OF XAU_NAS STARTING"
    )

    logger.info(
        "Markets: %s",
        ", ".join(MARKETS.keys())
    )

    logger.info(
        "===================================="
    )

    # Render health server

    Thread(
        target=run_web_server,
        daemon=True
    ).start()

    # Telegram

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )

    application.add_handler(
        CommandHandler(
            "watchlist",
            watchlist_command
        )
    )

    application.add_handler(
        CommandHandler(
            "scan",
            scan_command
        )
    )

    application.add_handler(
        CommandHandler(
            "scalp",
            scalp_command
        )
    )

    application.add_handler(
        CommandHandler(
            "normal",
            normal_command
        )
    )

    application.add_handler(
        CommandHandler(
            "signals",
            signals_command
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "🚀 Telegram bot online."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
