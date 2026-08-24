import os
import time
import asyncio
import logging
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ============================================================
# KING OF XAU/NAS
# COMPLETE REPLACEMENT BOT
# ============================================================

# -----------------------------
# ENVIRONMENT
# -----------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

PORT = int(os.getenv("PORT", "10000"))

# Optional:
# TELEGRAM_CHAT_ID can be set on Render.
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# -----------------------------
# MARKET SETTINGS
# -----------------------------

XAU_SYMBOL = "XAU/USD"

# NAS FALLBACK ORDER
NAS_SYMBOLS = [
    "NDX",
    "IXIC",
    "NAS100",
    "US100",
]

MAIN_INTERVAL = "15min"
HTF_INTERVAL = "1h"

OUTPUT_SIZE = 100

SCAN_INTERVAL_SECONDS = 300

REQUEST_TIMEOUT = 20

# Minimum confidence required to send signal
MIN_CONFIDENCE = 82

# Avoid repeatedly sending the same signal
SIGNAL_COOLDOWN_SECONDS = 1800

# -----------------------------
# LOGGING
# -----------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("KING_OF_XAU_NAS")

# -----------------------------
# FLASK SERVER
# -----------------------------

app = Flask(__name__)

START_TIME = time.time()

LAST_SCAN_TIME = None

HEALTH = {
    "scanner": "RUNNING",
    "market_data": "DISCONNECTED",
    "telegram": "DISCONNECTED",
    "xau": {
        "status": "UNKNOWN",
        "symbol": XAU_SYMBOL,
        "price": None,
    },
    "nas": {
        "status": "UNKNOWN",
        "symbol": None,
        "price": None,
    },
}

# -----------------------------
# CACHE
# -----------------------------

MARKET_CACHE = {}

CACHE_SECONDS = 45

# NAS working symbol
working_nas_symbol = None

# Prevent repeated alerts
LAST_SIGNAL = {}

# Telegram application
telegram_app = None

# Stop event
STOP_EVENT = threading.Event()


# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/")
def home():
    return jsonify({
        "bot": "KING OF XAU/NAS",
        "status": "RUNNING",
        "scanner": HEALTH["scanner"],
        "market_data": HEALTH["market_data"],
        "telegram": HEALTH["telegram"],
        "xau": HEALTH["xau"],
        "nas": HEALTH["nas"],
        "last_scan": LAST_SCAN_TIME,
    })


@app.route("/health")
def health():
    return jsonify(HEALTH)


@app.route("/ping")
def ping():
    return "KING OF XAU/NAS ONLINE", 200


def run_flask():
    try:
        app.run(
            host="0.0.0.0",
            port=PORT,
            debug=False,
            use_reloader=False,
        )
    except Exception as e:
        logger.error("Flask error: %s", e)


# ============================================================
# TWELVE DATA
# ============================================================

def twelve_data_url(endpoint):
    return f"https://api.twelvedata.com/{endpoint}"


def request_twelve_data(params):
    params = dict(params)
    params["apikey"] = TWELVE_DATA_API_KEY

    try:
        response = requests.get(
            twelve_data_url("time_series"),
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:
            logger.warning("Twelve Data rate limit reached.")
            return None

        if response.status_code != 200:
            logger.warning(
                "Twelve Data HTTP %s",
                response.status_code,
            )
            return None

        data = response.json()

        if "code" in data and data.get("code") not in (200, None):
            logger.warning(
                "Twelve Data error: %s",
                data.get("message", "Unknown error"),
            )
            return None

        values = data.get("values")

        if not values:
            return None

        return data

    except requests.RequestException as e:
        logger.warning("Market request failed: %s", e)
        return None

    except Exception as e:
        logger.exception("Unexpected market-data error: %s", e)
        return None


# ============================================================
# GET CANDLES
# ============================================================

def get_candles(symbol, interval=MAIN_INTERVAL):
    cache_key = f"{symbol}_{interval}"

    now = time.time()

    # Use cache when available
    cached = MARKET_CACHE.get(cache_key)

    if cached:
        timestamp, candles = cached

        if now - timestamp < CACHE_SECONDS:
            logger.info(
                "Using cached market data: %s %s",
                symbol,
                interval,
            )
            return candles

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": OUTPUT_SIZE,
        "format": "JSON",
    }

    data = request_twelve_data(params)

    if not data:
        return None

    values = data.get("values", [])

    if len(values) < 30:
        logger.warning(
            "Not enough candles for %s",
            symbol,
        )
        return None

    candles = []

    for item in reversed(values):
        try:
            candles.append({
                "datetime": item.get("datetime"),
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
            })
        except Exception:
            continue

    if len(candles) < 30:
        return None

    MARKET_CACHE[cache_key] = (
        now,
        candles,
    )

    return candles


# ============================================================
# NAS100 FALLBACK
# ============================================================

def get_nas100_candles(interval=MAIN_INTERVAL):
    """
    Automatically tries several NASDAQ/NAS100 symbols.

    Priority:
        NDX
        IXIC
        NAS100
        US100

    The first working symbol is remembered.
    """

    global working_nas_symbol

    # Try known working symbol first
    symbols_to_try = []

    if working_nas_symbol:
        symbols_to_try.append(working_nas_symbol)

    for symbol in NAS_SYMBOLS:
        if symbol not in symbols_to_try:
            symbols_to_try.append(symbol)

    for symbol in symbols_to_try:

        logger.info(
            "Trying NAS100 symbol: %s",
            symbol,
        )

        candles = get_candles(
            symbol,
            interval,
        )

        if candles:
            working_nas_symbol = symbol

            logger.info(
                "NAS100 CONNECTED using symbol: %s",
                symbol,
            )

            return symbol, candles

        logger.warning(
            "NAS100 symbol failed: %s",
            symbol,
        )

    working_nas_symbol = None

    logger.error(
        "ALL NAS100 fallback symbols failed."
    )

    return None, None


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema_value = sum(values[:period]) / period

    for price in values[period:]:
        ema_value = (
            (price - ema_value) * multiplier
        ) + ema_value

    return ema_value


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

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

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
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(
                current["high"]
                - previous["close"]
            ),
            abs(
                current["low"]
                - previous["close"]
            ),
        )

        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    return sum(
        true_ranges[-period:]
    ) / period


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_market(candles):
    if not candles or len(candles) < 60:
        return None

    closes = [x["close"] for x in candles]

    highs = [x["high"] for x in candles]
    lows = [x["low"] for x in candles]

    price = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    rsi14 = calculate_rsi(
        closes,
        14,
    )

    atr14 = calculate_atr(
        candles,
        14,
    )

    if (
        ema20 is None
        or ema50 is None
        or rsi14 is None
        or atr14 is None
    ):
        return None

    # Recent structure
    recent_high = max(
        highs[-20:]
    )

    recent_low = min(
        lows[-20:]
    )

    previous_close = closes[-2]

    momentum = price - previous_close

    bullish = (
        price > ema20
        and ema20 > ema50
    )

    bearish = (
        price < ema20
        and ema20 < ema50
    )

    return {
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi14,
        "atr": atr14,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "momentum": momentum,
        "bullish": bullish,
        "bearish": bearish,
    }


# ============================================================
# HIGHER TIMEFRAME TREND
# ============================================================

def get_htf_trend(symbol):
    candles = get_candles(
        symbol,
        HTF_INTERVAL,
    )

    if not candles:
        return "UNKNOWN"

    closes = [
        x["close"]
        for x in candles
    ]

    e20 = ema(
        closes,
        20,
    )

    e50 = ema(
        closes,
        50,
    )

    price = closes[-1]

    if e20 is None or e50 is None:
        return "UNKNOWN"

    if price > e20 and e20 > e50:
        return "BULLISH"

    if price < e20 and e20 < e50:
        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# SIGNAL GENERATOR
# ============================================================

def generate_signal(symbol, analysis, htf_trend):
    if not analysis:
        return None

    price = analysis["price"]
    ema20 = analysis["ema20"]
    ema50 = analysis["ema50"]
    rsi = analysis["rsi"]
    atr = analysis["atr"]

    bullish_score = 0
    bearish_score = 0

    # ---------------------------------
    # EMA TREND
    # ---------------------------------

    if price > ema20:
        bullish_score += 2

    if price < ema20:
        bearish_score += 2

    if ema20 > ema50:
        bullish_score += 2

    if ema20 < ema50:
        bearish_score += 2

    # ---------------------------------
    # RSI
    # ---------------------------------

    if 50 <= rsi <= 68:
        bullish_score += 2

    if 32 <= rsi <= 50:
        bearish_score += 2

    # Avoid chasing extreme RSI
    if rsi > 75:
        bullish_score -= 1

    if rsi < 25:
        bearish_score -= 1

    # ---------------------------------
    # HIGHER TIMEFRAME
    # ---------------------------------

    if htf_trend == "BULLISH":
        bullish_score += 2

    if htf_trend == "BEARISH":
        bearish_score += 2

    # ---------------------------------
    # MOMENTUM
    # ---------------------------------

    if analysis["momentum"] > 0:
        bullish_score += 1

    if analysis["momentum"] < 0:
        bearish_score += 1

    # ---------------------------------
    # DETERMINE DIRECTION
    # ---------------------------------

    if bullish_score > bearish_score:
        direction = "BUY"
        score = bullish_score
    elif bearish_score > bullish_score:
        direction = "SELL"
        score = bearish_score
    else:
        return None

    # Maximum practical score = 10
    confidence = min(
        98,
        int(
            55
            + (score * 4)
        ),
    )

    if confidence < MIN_CONFIDENCE:
        return None

    # ---------------------------------
    # RISK LEVELS
    # ---------------------------------

    if direction == "BUY":

        entry = price

        sl = entry - (
            atr * 1.5
        )

        tp1 = entry + (
            atr * 1.0
        )

        tp2 = entry + (
            atr * 2.0
        )

        tp3 = entry + (
            atr * 3.0
        )

    else:

        entry = price

        sl = entry + (
            atr * 1.5
        )

        tp1 = entry - (
            atr * 1.0
        )

        tp2 = entry - (
            atr * 2.0
        )

        tp3 = entry - (
            atr * 3.0
        )

    return {
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "htf": htf_trend,
    }


# ============================================================
# FORMAT PRICE
# ============================================================

def format_price(price):
    if price is None:
        return "N/A"

    if price >= 1000:
        return f"{price:,.2f}"

    if price >= 100:
        return f"{price:,.2f}"

    return f"{price:.5f}"


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def build_signal_message(signal):
    direction = signal["direction"]

    emoji = (
        "🟢"
        if direction == "BUY"
        else "🔴"
    )

    symbol = signal["symbol"]

    return (
        f"👑 <b>KING OF XAU/NAS</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>{direction} SIGNAL</b>\n\n"
        f"📊 <b>Market:</b> {symbol}\n"
        f"🎯 <b>Confidence:</b> "
        f"{signal['confidence']}%\n"
        f"⏱️ <b>Timeframe:</b> 15M\n"
        f"📈 <b>HTF Trend:</b> "
        f"{signal['htf']}\n\n"
        f"💰 <b>Entry:</b> "
        f"{format_price(signal['entry'])}\n"
        f"🛑 <b>Stop Loss:</b> "
        f"{format_price(signal['sl'])}\n"
        f"🎯 <b>TP1:</b> "
        f"{format_price(signal['tp1'])}\n"
        f"🎯 <b>TP2:</b> "
        f"{format_price(signal['tp2'])}\n"
        f"🎯 <b>TP3:</b> "
        f"{format_price(signal['tp3'])}\n\n"
        f"📐 <b>EMA20:</b> "
        f"{format_price(signal['ema20'])}\n"
        f"📐 <b>EMA50:</b> "
        f"{format_price(signal['ema50'])}\n"
        f"📊 <b>RSI:</b> "
        f"{signal['rsi']:.1f}\n"
        f"📏 <b>ATR:</b> "
        f"{format_price(signal['atr'])}\n\n"
        f"⚠️ <i>Market information is for "
        f"analysis only. Not financial advice.</i>"
    )


# ============================================================
# TELEGRAM SEND
# ============================================================

async def send_message(text, chat_id=None):
    global telegram_app

    if not telegram_app:
        logger.warning(
            "Telegram application unavailable."
        )
        return False

    target = (
        chat_id
        or TELEGRAM_CHAT_ID
    )

    if not target:
        logger.warning(
            "No TELEGRAM_CHAT_ID configured."
        )
        return False

    try:
        await telegram_app.bot.send_message(
            chat_id=target,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

        return True

    except Exception as e:
        logger.error(
            "Telegram send error: %s",
            e,
        )

        return False


# ============================================================
# SIGNAL COOLDOWN
# ============================================================

def can_send_signal(symbol, direction):
    key = f"{symbol}_{direction}"

    now = time.time()

    last = LAST_SIGNAL.get(key)

    if last:
        if (
            now - last
            < SIGNAL_COOLDOWN_SECONDS
        ):
            return False

    LAST_SIGNAL[key] = now

    return True


# ============================================================
# SCAN XAU
# ============================================================

async def scan_xau():
    symbol = XAU_SYMBOL

    candles = get_candles(
        symbol,
        MAIN_INTERVAL,
    )

    if not candles:
        HEALTH["xau"] = {
            "status": "ERROR",
            "symbol": symbol,
            "price": None,
        }

        return

    analysis = analyze_market(
        candles
    )

    if not analysis:
        return

    HEALTH["xau"] = {
        "status": "OK",
        "symbol": symbol,
        "price": analysis["price"],
    }

    htf = get_htf_trend(symbol)

    signal = generate_signal(
        symbol,
        analysis,
        htf,
    )

    if signal:
        if can_send_signal(
            symbol,
            signal["direction"],
        ):

            text = build_signal_message(
                signal
            )

            await send_message(text)


# ============================================================
# SCAN NAS100
# ============================================================

async def scan_nas():
    symbol, candles = get_nas100_candles(
        MAIN_INTERVAL
    )

    if not symbol or not candles:

        HEALTH["nas"] = {
            "status": "ERROR",
            "symbol": "N/A",
            "price": None,
        }

        return

    analysis = analyze_market(
        candles
    )

    if not analysis:
        HEALTH["nas"] = {
            "status": "ERROR",
            "symbol": symbol,
            "price": None,
        }

        return

    HEALTH["nas"] = {
        "status": "OK",
        "symbol": symbol,
        "price": analysis["price"],
    }

    htf = get_htf_trend(symbol)

    signal = generate_signal(
        symbol,
        analysis,
        htf,
    )

    if signal:
        if can_send_signal(
            symbol,
            signal["direction"],
        ):

            text = build_signal_message(
                signal
            )

            await send_message(text)


# ============================================================
# COMPLETE MARKET SCAN
# ============================================================

async def run_scan():
    global LAST_SCAN_TIME

    LAST_SCAN_TIME = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    logger.info(
        "========================================"
    )

    logger.info(
        "KING OF XAU/NAS MARKET SCAN"
    )

    logger.info(
        "========================================"
    )

    HEALTH["market_data"] = "CONNECTED"

    try:
        await scan_xau()
    except Exception as e:
        logger.exception(
            "XAU scan error: %s",
            e,
        )

    # Small delay to avoid hammering API
    await asyncio.sleep(2)

    try:
        await scan_nas()
    except Exception as e:
        logger.exception(
            "NAS scan error: %s",
            e,
        )

    logger.info(
        "XAU: %s | %s",
        HEALTH["xau"]["status"],
        HEALTH["xau"]["price"],
    )

    logger.info(
        "NAS: %s | %s | %s",
        HEALTH["nas"]["status"],
        HEALTH["nas"]["symbol"],
        HEALTH["nas"]["price"],
    )


# ============================================================
# BACKGROUND SCANNER
# ============================================================

async def scanner_loop():
    logger.info(
        "Background scanner started."
    )

    # Initial scan
    await run_scan()

    while not STOP_EVENT.is_set():

        try:
            await asyncio.sleep(
                SCAN_INTERVAL_SECONDS
            )

            if STOP_EVENT.is_set():
                break

            await run_scan()

        except asyncio.CancelledError:
            break

        except Exception as e:
            logger.exception(
                "Scanner loop error: %s",
                e,
            )

            await asyncio.sleep(30)


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    HEALTH["telegram"] = "CONNECTED"

    message = (
        "👑 <b>KING OF XAU/NAS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🟢 Scanner: RUNNING\n"
        "🟢 Market Data: CONNECTED\n"
        "🟢 Telegram: CONNECTED\n\n"
        "📊 <b>Markets</b>\n"
        "🟡 XAUUSD\n"
        "🔵 NAS100\n\n"
        "Use /status to check the scanner.\n"
        "Use /scan to run a manual scan.\n"
        "Use /nas to test NAS100.\n"
        "Use /gold to test XAUUSD."
    )

    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
    )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    nas_symbol = (
        working_nas_symbol
        or "AUTO"
    )

    message = (
        "👑 <b>KING OF XAU/NAS — HEALTH</b>\n\n"
        "🟢 Scanner: <b>RUNNING</b>\n"
        f"🟢 Market Data: <b>"
        f"{HEALTH['market_data']}</b>\n"
        "🟢 Telegram: <b>CONNECTED</b>\n\n"
        f"🟡 XAUUSD: "
        f"<b>{HEALTH['xau']['status']}</b>\n"
        f"   Symbol: {HEALTH['xau']['symbol']}\n"
        f"   Price: "
        f"{format_price(HEALTH['xau']['price'])}\n\n"
        f"🔵 NAS100: "
        f"<b>{HEALTH['nas']['status']}</b>\n"
        f"   Symbol: "
        f"{HEALTH['nas']['symbol'] or nas_symbol}\n"
        f"   Price: "
        f"{format_price(HEALTH['nas']['price'])}\n\n"
        f"⏱️ Last scan: "
        f"{LAST_SCAN_TIME or 'Not yet'}"
    )

    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
    )


async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "🔎 <b>Manual scan started...</b>",
        parse_mode=ParseMode.HTML,
    )

    await run_scan()

    await update.message.reply_text(
        "✅ <b>Manual scan completed.</b>\n\n"
        "Use /status to see the latest market state.",
        parse_mode=ParseMode.HTML,
    )


async def nas_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "🔵 <b>Testing NAS100 fallback...</b>",
        parse_mode=ParseMode.HTML,
    )

    symbol, candles = get_nas100_candles(
        MAIN_INTERVAL
    )

    if not symbol or not candles:
        await update.message.reply_text(
            "🔴 <b>NAS100 FAILED</b>\n\n"
            "Tried:\n"
            "• NDX\n"
            "• IXIC\n"
            "• NAS100\n"
            "• US100\n\n"
            "None returned valid Twelve Data candles.",
            parse_mode=ParseMode.HTML,
        )

        return

    analysis = analyze_market(
        candles
    )

    if not analysis:
        await update.message.reply_text(
            f"🟡 NAS symbol <b>{symbol}</b> "
            "connected, but technical data "
            "is insufficient.",
            parse_mode=ParseMode.HTML,
        )

        return

    HEALTH["nas"] = {
        "status": "OK",
        "symbol": symbol,
        "price": analysis["price"],
    }

    await update.message.reply_text(
        f"🟢 <b>NAS100 CONNECTED</b>\n\n"
        f"Symbol: <b>{symbol}</b>\n"
        f"Price: <b>"
        f"{format_price(analysis['price'])}</b>\n"
        f"EMA20: {format_price(analysis['ema20'])}\n"
        f"EMA50: {format_price(analysis['ema50'])}\n"
        f"RSI14: {analysis['rsi']:.1f}\n"
        f"ATR14: {format_price(analysis['atr'])}",
        parse_mode=ParseMode.HTML,
    )


async def gold_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "🟡 <b>Testing XAUUSD...</b>",
        parse_mode=ParseMode.HTML,
    )

    candles = get_candles(
        XAU_SYMBOL,
        MAIN_INTERVAL,
    )

    if not candles:
        await update.message.reply_text(
            "🔴 XAUUSD market data failed.",
            parse_mode=ParseMode.HTML,
        )

        return

    analysis = analyze_market(
        candles
    )

    if not analysis:
        await update.message.reply_text(
            "🟡 XAUUSD connected, but "
            "technical data is insufficient.",
            parse_mode=ParseMode.HTML,
        )

        return

    HEALTH["xau"] = {
        "status": "OK",
        "symbol": XAU_SYMBOL,
        "price": analysis["price"],
    }

    await update.message.reply_text(
        f"🟢 <b>XAUUSD CONNECTED</b>\n\n"
        f"Symbol: <b>{XAU_SYMBOL}</b>\n"
        f"Price: <b>"
        f"{format_price(analysis['price'])}</b>\n"
        f"EMA20: {format_price(analysis['ema20'])}\n"
        f"EMA50: {format_price(analysis['ema50'])}\n"
        f"RSI14: {analysis['rsi']:.1f}\n"
        f"ATR14: {format_price(analysis['atr'])}",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# TELEGRAM ERROR HANDLER
# ============================================================

async def telegram_error_handler(
    update,
    context,
):
    logger.error(
        "Telegram error: %s",
        context.error,
    )


# ============================================================
# TELEGRAM STARTUP
# ============================================================

async def telegram_main():
    global telegram_app

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not TWELVE_DATA_API_KEY:
        raise RuntimeError(
            "TWELVE_DATA_API_KEY is missing."
        )

    telegram_app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    telegram_app.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "scan",
            scan_command,
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "nas",
            nas_command,
        )
    )

    telegram_app.add_handler(
        CommandHandler(
            "gold",
            gold_command,
        )
    )

    telegram_app.add_error_handler(
        telegram_error_handler
    )

    HEALTH["telegram"] = "CONNECTED"

    logger.info(
        "Telegram bot starting..."
    )

    await telegram_app.initialize()

    await telegram_app.start()

    await telegram_app.updater.start_polling(
        drop_pending_updates=True
    )

    logger.info(
        "Telegram polling started."
    )

    # Run scanner in the SAME asyncio loop.
    scanner_task = asyncio.create_task(
        scanner_loop()
    )

    try:
        while not STOP_EVENT.is_set():
            await asyncio.sleep(1)

    finally:

        scanner_task.cancel()

        try:
            await scanner_task
        except asyncio.CancelledError:
            pass

        await telegram_app.updater.stop()

        await telegram_app.stop()

        await telegram_app.shutdown()


# ============================================================
# MAIN
# ============================================================

def main():
    logger.info(
        "========================================"
    )

    logger.info(
        "👑 KING OF XAU/NAS STARTING"
    )

    logger.info(
        "========================================"
    )

    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not configured."
        )

    if not TWELVE_DATA_API_KEY:
        logger.error(
            "TWELVE_DATA_API_KEY is not configured."
        )

    # Start Render web server
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )

    flask_thread.start()

    logger.info(
        "Flask health server started on port %s",
        PORT,
    )

    try:
        asyncio.run(
            telegram_main()
        )

    except KeyboardInterrupt:
        logger.info(
            "Bot stopped manually."
        )

    except Exception as e:
        logger.exception(
            "Fatal bot error: %s",
            e,
        )

    finally:
        STOP_EVENT.set()


if __name__ == "__main__":
    main()
