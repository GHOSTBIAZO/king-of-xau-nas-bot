import os
import time
import asyncio
import logging
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ============================================================
# 👑 KING OF XAU/NAS — XAUUSD SLINGSHOT
# XAU/USD ONLY
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

PORT = int(os.getenv("PORT", "10000"))

# ============================================================
# MARKET CONFIG
# ============================================================

SYMBOL = "XAU/USD"

MAIN_INTERVAL = "15min"
HTF_INTERVAL = "1h"
ENTRY_INTERVAL = "5min"

OUTPUT_SIZE = 100

# Scan every 5 minutes
SCAN_INTERVAL = 300

# Minimum signal confidence
MIN_CONFIDENCE = 82

# Prevent duplicate signals
SIGNAL_COOLDOWN = 1800

# API cache
CACHE_SECONDS = 45

REQUEST_TIMEOUT = 20

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("KING_OF_XAU_NAS")

# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)

LAST_SCAN = None
LAST_SIGNAL = None

HEALTH = {
    "scanner": "RUNNING",
    "market_data": "CONNECTED",
    "telegram": "CONNECTED",
    "xau": {
        "status": "UNKNOWN",
        "symbol": SYMBOL,
        "price": None,
    },
}

# ============================================================
# CACHE
# ============================================================

CACHE = {}

LAST_SENT_SIGNAL = None
LAST_SENT_TIME = 0

STOP_EVENT = threading.Event()

telegram_app = None


# ============================================================
# WEB HEALTH
# ============================================================

@app.route("/")
def home():
    return jsonify({
        "bot": "KING OF XAU/NAS",
        "mode": "XAUUSD SLINGSHOT",
        "status": "RUNNING",
        "health": HEALTH,
        "last_scan": LAST_SCAN,
        "last_signal": LAST_SIGNAL,
    })


@app.route("/health")
def health():
    return jsonify(HEALTH)


@app.route("/ping")
def ping():
    return "KING OF XAU/NAS ONLINE", 200


def run_flask():
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )


# ============================================================
# TWELVE DATA
# ============================================================

def get_market_data(symbol, interval):
    key = f"{symbol}_{interval}"

    now = time.time()

    # -----------------------------
    # CACHE
    # -----------------------------

    if key in CACHE:

        timestamp, cached_data = CACHE[key]

        if now - timestamp < CACHE_SECONDS:

            logger.info(
                "Using cached market data: %s %s",
                symbol,
                interval,
            )

            return cached_data

    # -----------------------------
    # API
    # -----------------------------

    url = "https://api.twelvedata.com/time_series"

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": OUTPUT_SIZE,
        "format": "JSON",
        "apikey": TWELVE_DATA_API_KEY,
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:

            logger.warning(
                "Twelve Data rate limit reached."
            )

            return None

        if response.status_code != 200:

            logger.warning(
                "Twelve Data HTTP error: %s",
                response.status_code,
            )

            return None

        data = response.json()

        if "values" not in data:

            logger.warning(
                "Twelve Data error: %s",
                data.get(
                    "message",
                    "No candle data returned."
                ),
            )

            return None

        candles = []

        # Twelve Data normally returns newest first.
        # Reverse so calculations are chronological.
        for item in reversed(data["values"]):

            try:

                candles.append({
                    "datetime": item["datetime"],
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                })

            except Exception:
                continue

        if len(candles) < 60:

            logger.warning(
                "Insufficient candles: %s",
                len(candles),
            )

            return None

        CACHE[key] = (
            now,
            candles,
        )

        return candles

    except requests.RequestException as e:

        logger.warning(
            "Market-data request failed: %s",
            e,
        )

        return None

    except Exception as e:

        logger.exception(
            "Market-data error: %s",
            e,
        )

        return None


# ============================================================
# EMA
# ============================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    value = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        value = (
            (price - value) * multiplier
        ) + value

    return value


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

    avg_gain = (
        sum(gains[:period]) / period
    )

    avg_loss = (
        sum(losses[:period]) / period
    )

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

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    ranges = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"]
            - current["low"],

            abs(
                current["high"]
                - previous["close"]
            ),

            abs(
                current["low"]
                - previous["close"]
            ),
        )

        ranges.append(tr)

    if len(ranges) < period:
        return None

    return sum(
        ranges[-period:]
    ) / period


# ============================================================
# MARKET STRUCTURE
# ============================================================

def get_structure(candles):

    if len(candles) < 30:
        return "NEUTRAL"

    recent = candles[-20:]

    highs = [
        x["high"]
        for x in recent
    ]

    lows = [
        x["low"]
        for x in recent
    ]

    last = candles[-1]

    previous = candles[-2]

    recent_high = max(highs[:-2])
    recent_low = min(lows[:-2])

    if (
        last["close"] > recent_high
        and last["close"] > previous["close"]
    ):
        return "BULLISH_BREAK"

    if (
        last["close"] < recent_low
        and last["close"] < previous["close"]
    ):
        return "BEARISH_BREAK"

    if last["high"] > previous["high"]:
        return "BULLISH"

    if last["low"] < previous["low"]:
        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def detect_liquidity_sweep(candles):

    if len(candles) < 10:
        return "NONE"

    current = candles[-1]

    previous = candles[-6:-1]

    previous_high = max(
        x["high"]
        for x in previous
    )

    previous_low = min(
        x["low"]
        for x in previous
    )

    # Bullish liquidity sweep:
    # price takes previous low and closes back above it
    if (
        current["low"] < previous_low
        and current["close"] > previous_low
    ):
        return "BULLISH_SWEEP"

    # Bearish liquidity sweep:
    # price takes previous high and closes back below it
    if (
        current["high"] > previous_high
        and current["close"] < previous_high
    ):
        return "BEARISH_SWEEP"

    return "NONE"


# ============================================================
# FAIR VALUE GAP
# ============================================================

def detect_fvg(candles):

    if len(candles) < 5:
        return "NONE"

    a = candles[-3]
    c = candles[-1]

    # Bullish FVG
    if c["low"] > a["high"]:
        return "BULLISH_FVG"

    # Bearish FVG
    if c["high"] < a["low"]:
        return "BEARISH_FVG"

    return "NONE"


# ============================================================
# SLINGSHOT ENGINE
# ============================================================

def slingshot_signal(candles, htf_candles):

    if (
        not candles
        or not htf_candles
        or len(candles) < 60
        or len(htf_candles) < 60
    ):
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    htf_closes = [
        x["close"]
        for x in htf_candles
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

    htf_ema20 = calculate_ema(
        htf_closes,
        20,
    )

    htf_ema50 = calculate_ema(
        htf_closes,
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

    if any(
        x is None
        for x in [
            ema20,
            ema50,
            htf_ema20,
            htf_ema50,
            rsi,
            atr,
        ]
    ):
        return None

    structure = get_structure(
        candles
    )

    sweep = detect_liquidity_sweep(
        candles
    )

    fvg = detect_fvg(
        candles
    )

    # ========================================================
    # SCORE
    # ========================================================

    buy_score = 0
    sell_score = 0

    # -------------------------
    # EMA TREND
    # -------------------------

    if price > ema20:
        buy_score += 2

    if price < ema20:
        sell_score += 2

    if ema20 > ema50:
        buy_score += 2

    if ema20 < ema50:
        sell_score += 2

    # -------------------------
    # HTF TREND
    # -------------------------

    if (
        htf_ema20 > htf_ema50
        and price > htf_ema20
    ):
        buy_score += 2

    if (
        htf_ema20 < htf_ema50
        and price < htf_ema20
    ):
        sell_score += 2

    # -------------------------
    # RSI
    # -------------------------

    if 50 <= rsi <= 68:
        buy_score += 1

    if 32 <= rsi <= 50:
        sell_score += 1

    # -------------------------
    # STRUCTURE
    # -------------------------

    if structure in (
        "BULLISH",
        "BULLISH_BREAK",
    ):
        buy_score += 1

    if structure in (
        "BEARISH",
        "BEARISH_BREAK",
    ):
        sell_score += 1

    # -------------------------
    # LIQUIDITY SWEEP
    # -------------------------

    if sweep == "BULLISH_SWEEP":
        buy_score += 2

    if sweep == "BEARISH_SWEEP":
        sell_score += 2

    # -------------------------
    # FVG
    # -------------------------

    if fvg == "BULLISH_FVG":
        buy_score += 1

    if fvg == "BEARISH_FVG":
        sell_score += 1

    # ========================================================
    # SLINGSHOT TRIGGER
    # ========================================================

    direction = None

    if buy_score > sell_score:
        direction = "BUY"
        score = buy_score

    elif sell_score > buy_score:
        direction = "SELL"
        score = sell_score

    else:
        return None

    # Need strong alignment
    if score < 7:
        return None

    confidence = min(
        98,
        70 + (score * 3)
    )

    if confidence < MIN_CONFIDENCE:
        return None

    # ========================================================
    # ENTRY / RISK
    # ========================================================

    entry = price

    if direction == "BUY":

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
        "symbol": SYMBOL,
        "mode": "SLINGSHOT",
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
        "structure": structure,
        "sweep": sweep,
        "fvg": fvg,
    }


# ============================================================
# PRICE FORMAT
# ============================================================

def fmt(price):

    if price is None:
        return "N/A"

    return f"{price:,.2f}"


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def signal_message(signal):

    if signal["direction"] == "BUY":

        header = "🟢 BUY"

    else:

        header = "🔴 SELL"

    return (
        "👑 <b>KING OF XAU/NAS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🏹 <b>SLINGSHOT {header}</b>\n\n"

        f"🟡 <b>XAU/USD</b>\n"
        f"📊 Confidence: "
        f"<b>{signal['confidence']}%</b>\n"
        f"⏱️ Timeframe: <b>15M</b>\n\n"

        f"💰 Entry: "
        f"<b>{fmt(signal['entry'])}</b>\n"
        f"🛑 Stop Loss: "
        f"<b>{fmt(signal['sl'])}</b>\n\n"

        f"🎯 TP1: <b>{fmt(signal['tp1'])}</b>\n"
        f"🎯 TP2: <b>{fmt(signal['tp2'])}</b>\n"
        f"🎯 TP3: <b>{fmt(signal['tp3'])}</b>\n\n"

        f"📈 EMA20: {fmt(signal['ema20'])}\n"
        f"📉 EMA50: {fmt(signal['ema50'])}\n"
        f"📊 RSI14: {signal['rsi']:.1f}\n"
        f"📏 ATR14: {fmt(signal['atr'])}\n\n"

        f"🏗 Structure: "
        f"{signal['structure']}\n"
        f"💧 Liquidity: "
        f"{signal['sweep']}\n"
        f"🧩 FVG: "
        f"{signal['fvg']}\n\n"

        "⚠️ <i>Market information is for "
        "analysis only. Not financial advice.</i>"
    )


# ============================================================
# TELEGRAM MENU
# ============================================================

def main_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "🏹 SLINGSHOT",
                callback_data="slingshot"
            ),
        ],

        [
            InlineKeyboardButton(
                "🟢 BUY",
                callback_data="buy"
            ),

            InlineKeyboardButton(
                "🔴 SELL",
                callback_data="sell"
            ),
        ],

        [
            InlineKeyboardButton(
                "🔎 SCAN NOW",
                callback_data="scan"
            ),

            InlineKeyboardButton(
                "❤️ HEALTH",
                callback_data="health"
            ),
        ],

    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# TELEGRAM /START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "👑 <b>KING OF XAU/NAS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🟡 <b>XAU/USD SIGNAL SYSTEM</b>\n\n"

        "🏹 <b>SLINGSHOT</b>\n"
        "Finds high-confidence Gold setups.\n\n"

        "🟢 <b>BUY</b>\n"
        "Direct bullish scan.\n\n"

        "🔴 <b>SELL</b>\n"
        "Direct bearish scan.\n\n"

        "📊 Timeframe: 15M\n"
        "📈 HTF confirmation: 1H\n\n"

        "Select an option below:"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# ============================================================
# STATUS
# ============================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "👑 <b>KING OF XAU/NAS — HEALTH</b>\n\n"

        "🟢 Scanner: <b>RUNNING</b>\n"
        "🟢 Market Data: <b>"
        f"{HEALTH['market_data']}</b>\n"
        "🟢 Telegram: <b>CONNECTED</b>\n\n"

        "🟡 XAUUSD: "
        f"<b>{HEALTH['xau']['status']}</b>\n"
        f"   Symbol: {SYMBOL}\n"
        f"   Price: "
        f"<b>{fmt(HEALTH['xau']['price'])}</b>\n\n"

        f"🏹 Mode: <b>SLINGSHOT</b>\n"
        f"⏱️ Last scan: "
        f"{LAST_SCAN or 'Not yet'}"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# ============================================================
# RUN XAU ANALYSIS
# ============================================================

def analyse_xau():

    candles = get_market_data(
        SYMBOL,
        MAIN_INTERVAL,
    )

    if not candles:

        HEALTH["xau"] = {
            "status": "ERROR",
            "symbol": SYMBOL,
            "price": None,
        }

        return None

    price = candles[-1]["close"]

    HEALTH["xau"] = {
        "status": "OK",
        "symbol": SYMBOL,
        "price": price,
    }

    htf = get_market_data(
        SYMBOL,
        HTF_INTERVAL,
    )

    if not htf:
        return None

    return slingshot_signal(
        candles,
        htf,
    )


# ============================================================
# SEND SIGNAL
# ============================================================

async def send_signal(signal):

    global LAST_SENT_SIGNAL
    global LAST_SENT_TIME
    global LAST_SIGNAL

    if not signal:
        return False

    direction = signal["direction"]

    signal_key = (
        f"{SYMBOL}_{direction}"
    )

    now = time.time()

    # Duplicate protection
    if (
        LAST_SENT_SIGNAL == signal_key
        and now - LAST_SENT_TIME
        < SIGNAL_COOLDOWN
    ):
        logger.info(
            "Duplicate signal suppressed."
        )

        return False

    LAST_SENT_SIGNAL = signal_key
    LAST_SENT_TIME = now

    LAST_SIGNAL = signal

    text = signal_message(
        signal
    )

    if not TELEGRAM_CHAT_ID:

        logger.warning(
            "TELEGRAM_CHAT_ID not configured."
        )

        return False

    try:

        await telegram_app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

        logger.info(
            "SIGNAL SENT: %s %s",
            direction,
            signal["confidence"],
        )

        return True

    except Exception as e:

        logger.error(
            "Signal send error: %s",
            e,
        )

        return False


# ============================================================
# AUTOMATIC SCAN
# ============================================================

async def perform_scan():

    global LAST_SCAN

    LAST_SCAN = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    logger.info(
        "======================================"
    )

    logger.info(
        "🏹 SLINGSHOT XAU/USD SCAN"
    )

    logger.info(
        "======================================"
    )

    signal = analyse_xau()

    if not signal:

        logger.info(
            "No qualifying Slingshot signal."
        )

        return

    logger.info(
        "SLINGSHOT SIGNAL: %s",
        signal["direction"],
    )

    logger.info(
        "Confidence: %s%%",
        signal["confidence"],
    )

    logger.info(
        "Entry: %.2f",
        signal["entry"],
    )

    await send_signal(
        signal
    )


# ============================================================
# BACKGROUND LOOP
# ============================================================

async def scanner_loop():

    logger.info(
        "🏹 Slingshot scanner started."
    )

    # Scan immediately
    await perform_scan()

    while not STOP_EVENT.is_set():

        try:

            await asyncio.sleep(
                SCAN_INTERVAL
            )

            if STOP_EVENT.is_set():
                break

            await perform_scan()

        except asyncio.CancelledError:

            break

        except Exception as e:

            logger.exception(
                "Scanner error: %s",
                e,
            )

            await asyncio.sleep(
                30
            )


# ============================================================
# BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    action = query.data

    # ------------------------------------
    # HEALTH
    # ------------------------------------

    if action == "health":

        text = (
            "👑 <b>KING OF XAU/NAS — HEALTH</b>\n\n"
            "🟢 Scanner: <b>RUNNING</b>\n"
            "🟢 Market Data: <b>"
            f"{HEALTH['market_data']}</b>\n"
            "🟢 Telegram: <b>CONNECTED</b>\n\n"
            "🟡 XAUUSD: "
            f"<b>{HEALTH['xau']['status']}</b>\n"
            f"   Price: "
            f"<b>{fmt(HEALTH['xau']['price'])}</b>\n\n"
            "🏹 Mode: <b>SLINGSHOT</b>\n"
            f"⏱️ Last scan: "
            f"{LAST_SCAN or 'Not yet'}"
        )

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

        return

    # ------------------------------------
    # SCAN
    # ------------------------------------

    if action == "scan":

        await query.edit_message_text(
            "🔎 <b>Scanning XAU/USD...</b>\n\n"
            "🏹 Slingshot engine active.",
            parse_mode=ParseMode.HTML,
        )

        signal = analyse_xau()

        if signal:

            await send_signal(
                signal
            )

            await query.message.reply_text(
                signal_message(signal),
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )

        else:

            await query.message.reply_text(
                "🟡 <b>No qualifying signal.</b>\n\n"
                "The market does not currently "
                "meet the Slingshot conditions.",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )

        return

    # ------------------------------------
    # SLINGSHOT
    # ------------------------------------

    if action == "slingshot":

        await query.edit_message_text(
            "🏹 <b>SLINGSHOT SCAN</b>\n\n"
            "Checking XAU/USD for a "
            "high-confidence setup...",
            parse_mode=ParseMode.HTML,
        )

        signal = analyse_xau()

        if signal:

            await send_signal(
                signal
            )

            await query.message.reply_text(
                signal_message(signal),
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )

        else:

            await query.message.reply_text(
                "🏹 <b>SLINGSHOT — NO ENTRY</b>\n\n"
                "No qualifying BUY or SELL setup "
                "at the moment.",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )

        return

    # ------------------------------------
    # DIRECT BUY / SELL
    # ------------------------------------

    if action in (
        "buy",
        "sell",
    ):

        desired_direction = (
            "BUY"
            if action == "buy"
            else "SELL"
        )

        await query.edit_message_text(
            f"🔎 Checking XAU/USD for "
            f"<b>{desired_direction}</b>...",
            parse_mode=ParseMode.HTML,
        )

        signal = analyse_xau()

        if (
            signal
            and signal["direction"]
            == desired_direction
        ):

            await send_signal(
                signal
            )

            await query.message.reply_text(
                signal_message(signal),
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )

        else:

            emoji = (
                "🟢"
                if desired_direction == "BUY"
                else "🔴"
            )

            await query.message.reply_text(
                f"{emoji} <b>{desired_direction} "
                f"NOT CONFIRMED</b>\n\n"
                "The current XAU/USD conditions "
                "do not confirm this direction.",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )

        return


# ============================================================
# MANUAL COMMAND
# ============================================================

async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "🔎 <b>Scanning XAU/USD...</b>\n"
        "🏹 Slingshot engine active.",
        parse_mode=ParseMode.HTML,
    )

    signal = analyse_xau()

    if signal:

        await send_signal(
            signal
        )

        await update.message.reply_text(
            signal_message(signal),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

    else:

        await update.message.reply_text(
            "🟡 <b>No qualifying signal.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def telegram_error(
    update,
    context,
):

    logger.error(
        "Telegram error: %s",
        context.error,
    )


# ============================================================
# TELEGRAM MAIN
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
        CallbackQueryHandler(
            button_handler
        )
    )

    telegram_app.add_error_handler(
        telegram_error
    )

    HEALTH["telegram"] = "CONNECTED"

    await telegram_app.initialize()

    await telegram_app.start()

    await telegram_app.updater.start_polling(
        drop_pending_updates=True
    )

    logger.info(
        "Telegram polling started."
    )

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
        "======================================"
    )

    logger.info(
        "👑 KING OF XAU/NAS"
    )

    logger.info(
        "🏹 XAU/USD SLINGSHOT MODE"
    )

    logger.info(
        "======================================"
    )

    HEALTH["scanner"] = "RUNNING"

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )

    flask_thread.start()

    logger.info(
        "Render health server running on %s",
        PORT,
    )

    try:

        asyncio.run(
            telegram_main()
        )

    except KeyboardInterrupt:

        logger.info(
            "Bot stopped."
        )

    except Exception as e:

        logger.exception(
            "Fatal error: %s",
            e,
        )

    finally:

        STOP_EVENT.set()


if __name__ == "__main__":
    main()
