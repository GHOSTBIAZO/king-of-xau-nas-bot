import os
import time
import logging
import threading
from datetime import datetime, timezone

import requests
import pandas as pd
import numpy as np

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
# GOLD + NAS100 SIGNAL SCANNER
# ============================================================

BOT_NAME = "👑 KING OF XAU/NAS"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

PORT = int(os.getenv("PORT", "10000"))

# ------------------------------------------------------------
# MARKET SETTINGS
# ------------------------------------------------------------

MAIN_INTERVAL = "15min"
HTF_INTERVAL = "1h"
ENTRY_INTERVAL = "5min"

OUTPUT_SIZE = 100

SCAN_INTERVAL_SECONDS = 300
REQUEST_TIMEOUT = 20

MIN_CONFIDENCE = 82

# ------------------------------------------------------------
# SYMBOLS
# ------------------------------------------------------------

XAU_SYMBOLS = [
    "XAU/USD",
    "XAUUSD",
]

# Twelve Data symbol support can differ by plan.
# Try several possibilities automatically.
NAS_SYMBOLS = [
    "NDX",
    "NASDAQ",
    "NASDAQ:NDX",
    "US100",
    "NAS100",
    "NQ",
]

# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("KING_XAU_NAS")

# ------------------------------------------------------------
# FLASK / RENDER HEALTH SERVER
# ------------------------------------------------------------

app = Flask(__name__)

bot_started_at = datetime.now(timezone.utc)

last_scan_time = None

market_status = {
    "XAUUSD": {
        "status": "STARTING",
        "symbol": None,
        "price": None,
        "last_update": None,
        "error": None,
    },
    "NAS100": {
        "status": "STARTING",
        "symbol": None,
        "price": None,
        "last_update": None,
        "error": None,
    },
}

cached_data = {}

last_signals = {}

# Prevent multiple scanners from running.
scanner_lock = threading.Lock()


@app.route("/")
def home():
    return jsonify({
        "bot": BOT_NAME,
        "status": "RUNNING",
        "scanner": "RUNNING",
        "started_at": bot_started_at.isoformat(),
        "last_scan": last_scan_time,
        "markets": market_status,
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "scanner": "running",
        "markets": market_status,
    })


def run_flask():
    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True,
    )


# ============================================================
# TWELVE DATA
# ============================================================

def twelve_data_request(params):
    """
    Rate-limit-safe Twelve Data request.
    """

    if not TWELVE_DATA_API_KEY:
        raise RuntimeError("TWELVE_DATA_API_KEY is not configured")

    params = dict(params)
    params["apikey"] = TWELVE_DATA_API_KEY

    try:
        response = requests.get(
            "https://api.twelvedata.com/time_series",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:
            raise RuntimeError("Twelve Data rate limit reached (429)")

        response.raise_for_status()

        data = response.json()

        if data.get("status") == "error":
            raise RuntimeError(
                data.get("message", "Twelve Data returned an error")
            )

        if "values" not in data:
            raise RuntimeError("No market values returned")

        return data

    except requests.RequestException as exc:
        raise RuntimeError(f"Market request failed: {exc}") from exc


def get_market_data(symbol, interval=MAIN_INTERVAL, outputsize=OUTPUT_SIZE):
    """
    Get candles for a symbol.
    Uses cached data when possible.
    """

    cache_key = f"{symbol}:{interval}"

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "format": "JSON",
    }

    try:
        data = twelve_data_request(params)

        values = data.get("values", [])

        if not values:
            raise RuntimeError("Empty market data")

        df = pd.DataFrame(values)

        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(
                df["datetime"],
                errors="coerce",
            )

        numeric_columns = [
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        for column in numeric_columns:
            if column in df.columns:
                df[column] = pd.to_numeric(
                    df[column],
                    errors="coerce",
                )

        df = df.dropna(subset=["close"])

        df = df.sort_values("datetime")

        if len(df) < 30:
            raise RuntimeError(
                f"Insufficient candles returned: {len(df)}"
            )

        cached_data[cache_key] = {
            "data": df.copy(),
            "timestamp": time.time(),
        }

        return df, False

    except Exception as exc:

        logger.warning(
            "Market data failed for %s %s: %s",
            symbol,
            interval,
            exc,
        )

        cached = cached_data.get(cache_key)

        if cached:
            age = time.time() - cached["timestamp"]

            logger.warning(
                "Using cached market data for %s %s "
                "(age %.0fs)",
                symbol,
                interval,
                age,
            )

            return cached["data"].copy(), True

        raise


# ============================================================
# SYMBOL DISCOVERY
# ============================================================

def find_working_symbol(symbols, market_name):
    """
    Try symbols until Twelve Data returns valid data.

    This is the important NAS fallback system.
    """

    previous_symbol = market_status[market_name].get("symbol")

    candidates = list(symbols)

    # Try previously working symbol first.
    if previous_symbol and previous_symbol in candidates:
        candidates.remove(previous_symbol)
        candidates.insert(0, previous_symbol)

    last_error = None

    for symbol in candidates:

        try:

            logger.info(
                "Testing %s symbol: %s",
                market_name,
                symbol,
            )

            df, cached = get_market_data(
                symbol,
                MAIN_INTERVAL,
                OUTPUT_SIZE,
            )

            if df is None or df.empty:
                continue

            price = float(df["close"].iloc[-1])

            market_status[market_name] = {
                "status": "CACHED" if cached else "OK",
                "symbol": symbol,
                "price": price,
                "last_update": datetime.now(
                    timezone.utc
                ).isoformat(),
                "error": None,
            }

            logger.info(
                "%s connected using %s | price %.2f",
                market_name,
                symbol,
                price,
            )

            return symbol, df

        except Exception as exc:

            last_error = str(exc)

            logger.warning(
                "%s symbol failed: %s -> %s",
                market_name,
                symbol,
                exc,
            )

    market_status[market_name] = {
        "status": "ERROR",
        "symbol": previous_symbol,
        "price": None,
        "last_update": datetime.now(
            timezone.utc
        ).isoformat(),
        "error": last_error or "No supported symbol found",
    }

    return None, None


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def calculate_ema(series, period):
    return series.ewm(
        span=period,
        adjust=False,
    ).mean()


def calculate_rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False,
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    rsi = 100 - (
        100 / (1 + rs)
    )

    return rsi.fillna(50)


def calculate_atr(df, period=14):

    high = df["high"]
    low = df["low"]
    close = df["close"]

    previous_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - previous_close).abs()
    tr3 = (low - previous_close).abs()

    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1,
    ).max(axis=1)

    atr = true_range.ewm(
        alpha=1 / period,
        adjust=False,
    ).mean()

    return atr


def add_indicators(df):

    df = df.copy()

    df["ema20"] = calculate_ema(
        df["close"],
        20,
    )

    df["ema50"] = calculate_ema(
        df["close"],
        50,
    )

    df["rsi"] = calculate_rsi(
        df["close"],
        14,
    )

    df["atr"] = calculate_atr(
        df,
        14,
    )

    df["momentum"] = (
        df["close"] - df["close"].shift(5)
    )

    return df


# ============================================================
# MARKET STRUCTURE
# ============================================================

def market_structure(df):

    recent = df.tail(10)

    highest_high = recent["high"].max()
    lowest_low = recent["low"].min()

    current_close = float(
        recent["close"].iloc[-1]
    )

    if current_close > highest_high * 0.999:
        return "BULLISH"

    if current_close < lowest_low * 1.001:
        return "BEARISH"

    return "NEUTRAL"


def detect_liquidity_sweep(df):

    if len(df) < 6:
        return "NONE"

    previous = df.iloc[-2]
    current = df.iloc[-1]

    previous_high = df["high"].iloc[-6:-2].max()
    previous_low = df["low"].iloc[-6:-2].min()

    if (
        current["high"] > previous_high
        and current["close"] < previous_high
    ):
        return "BEARISH_SWEEP"

    if (
        current["low"] < previous_low
        and current["close"] > previous_low
    ):
        return "BULLISH_SWEEP"

    return "NONE"


def detect_fvg(df):

    if len(df) < 5:
        return "NONE"

    c1 = df.iloc[-3]
    c3 = df.iloc[-1]

    if c1["high"] < c3["low"]:
        return "BULLISH_FVG"

    if c1["low"] > c3["high"]:
        return "BEARISH_FVG"

    return "NONE"


# ============================================================
# SIGNAL ENGINE
# ============================================================

def analyze_market(df, symbol):

    df = add_indicators(df)

    current = df.iloc[-1]
    previous = df.iloc[-2]

    price = float(current["close"])

    ema20 = float(current["ema20"])
    ema50 = float(current["ema50"])

    rsi = float(current["rsi"])
    atr = float(current["atr"])

    momentum = float(current["momentum"])

    structure = market_structure(df)

    sweep = detect_liquidity_sweep(df)

    fvg = detect_fvg(df)

    buy_score = 0
    sell_score = 0

    reasons_buy = []
    reasons_sell = []

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if ema20 > ema50:

        buy_score += 2
        reasons_buy.append("EMA bullish")

    elif ema20 < ema50:

        sell_score += 2
        reasons_sell.append("EMA bearish")

    # --------------------------------------------------------
    # PRICE LOCATION
    # --------------------------------------------------------

    if price > ema20:
        buy_score += 1
        reasons_buy.append("Price above EMA20")

    if price < ema20:
        sell_score += 1
        reasons_sell.append("Price below EMA20")

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 52 <= rsi <= 70:

        buy_score += 2
        reasons_buy.append("RSI bullish")

    elif 30 <= rsi <= 48:

        sell_score += 2
        reasons_sell.append("RSI bearish")

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if momentum > 0:

        buy_score += 1
        reasons_buy.append("Positive momentum")

    elif momentum < 0:

        sell_score += 1
        reasons_sell.append("Negative momentum")

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    if structure == "BULLISH":

        buy_score += 2
        reasons_buy.append("Bullish structure")

    elif structure == "BEARISH":

        sell_score += 2
        reasons_sell.append("Bearish structure")

    # --------------------------------------------------------
    # LIQUIDITY SWEEP
    # --------------------------------------------------------

    if sweep == "BULLISH_SWEEP":

        buy_score += 2
        reasons_buy.append("Bullish liquidity sweep")

    elif sweep == "BEARISH_SWEEP":

        sell_score += 2
        reasons_sell.append("Bearish liquidity sweep")

    # --------------------------------------------------------
    # FVG
    # --------------------------------------------------------

    if fvg == "BULLISH_FVG":

        buy_score += 1
        reasons_buy.append("Bullish FVG")

    elif fvg == "BEARISH_FVG":

        sell_score += 1
        reasons_sell.append("Bearish FVG")

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    if buy_score > sell_score:
        direction = "BUY"
        score = buy_score
        reasons = reasons_buy

    elif sell_score > buy_score:
        direction = "SELL"
        score = sell_score
        reasons = reasons_sell

    else:
        return {
            "signal": "NONE",
            "symbol": symbol,
            "price": price,
            "confidence": 0,
        }

    # Convert score into confidence.
    confidence = min(
        98,
        int(
            55 + (
                score / 13
            ) * 43
        ),
    )

    if confidence < MIN_CONFIDENCE:

        return {
            "signal": "NONE",
            "symbol": symbol,
            "price": price,
            "confidence": confidence,
            "reason": "Confidence below threshold",
        }

    # --------------------------------------------------------
    # RISK MODEL
    # --------------------------------------------------------

    atr_multiplier = 1.5

    risk = max(
        atr * atr_multiplier,
        atr * 1.1,
    )

    if direction == "BUY":

        entry = price

        stop_loss = entry - risk

        tp1 = entry + risk * 1.0
        tp2 = entry + risk * 2.0

    else:

        entry = price

        stop_loss = entry + risk

        tp1 = entry - risk * 1.0
        tp2 = entry - risk * 2.0

    return {
        "signal": direction,
        "symbol": symbol,
        "price": price,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "confidence": confidence,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "structure": structure,
        "sweep": sweep,
        "fvg": fvg,
        "reasons": reasons,
    }


# ============================================================
# HIGHER TIMEFRAME CONFIRMATION
# ============================================================

def get_htf_bias(symbol):

    try:

        df, cached = get_market_data(
            symbol,
            HTF_INTERVAL,
            100,
        )

        df = add_indicators(df)

        current = df.iloc[-1]

        if current["ema20"] > current["ema50"]:
            return "BULLISH"

        if current["ema20"] < current["ema50"]:
            return "BEARISH"

        return "NEUTRAL"

    except Exception as exc:

        logger.warning(
            "HTF analysis failed for %s: %s",
            symbol,
            exc,
        )

        return "NEUTRAL"


# ============================================================
# PRICE FORMATTING
# ============================================================

def format_price(price, symbol):

    if price is None:
        return "N/A"

    if "XAU" in symbol.upper():
        return f"{price:,.2f}"

    return f"{price:,.2f}"


# ============================================================
# TELEGRAM
# ============================================================

async def safe_send(bot, chat_id, text):

    try:

        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    except Exception as exc:

        logger.error(
            "Telegram send failed: %s",
            exc,
        )


def build_signal_message(signal, market):

    symbol = signal["symbol"]

    direction = signal["signal"]

    emoji = "🟢" if direction == "BUY" else "🔴"

    price = format_price(
        signal["price"],
        symbol,
    )

    entry = format_price(
        signal["entry"],
        symbol,
    )

    sl = format_price(
        signal["stop_loss"],
        symbol,
    )

    tp1 = format_price(
        signal["tp1"],
        symbol,
    )

    tp2 = format_price(
        signal["tp2"],
        symbol,
    )

    reasons = signal.get(
        "reasons",
        [],
    )

    reason_text = "\n".join(
        f"• {reason}"
        for reason in reasons[:5]
    )

    return (
        f"👑 <b>KING OF XAU/NAS</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>{market} {direction}</b>\n\n"
        f"💰 <b>Price:</b> {price}\n"
        f"🎯 <b>Entry:</b> {entry}\n"
        f"🛑 <b>Stop Loss:</b> {sl}\n"
        f"💎 <b>TP1:</b> {tp1}\n"
        f"💎 <b>TP2:</b> {tp2}\n\n"
        f"📊 <b>Confidence:</b> "
        f"{signal['confidence']}%\n"
        f"⏱️ <b>Timeframe:</b> {MAIN_INTERVAL}\n\n"
        f"📈 <b>EMA20:</b> "
        f"{signal['ema20']:.2f}\n"
        f"📉 <b>EMA50:</b> "
        f"{signal['ema50']:.2f}\n"
        f"📊 <b>RSI:</b> "
        f"{signal['rsi']:.1f}\n"
        f"🌊 <b>ATR:</b> "
        f"{signal['atr']:.2f}\n"
        f"🏗️ <b>Structure:</b> "
        f"{signal['structure']}\n\n"
        f"<b>Confirmation</b>\n"
        f"{reason_text}\n\n"
        f"⚠️ <i>Market information is for "
        f"analysis only. Not financial advice.</i>"
    )


# ============================================================
# DUPLICATE SIGNAL PROTECTION
# ============================================================

def signal_key(signal):

    return (
        signal["symbol"],
        signal["signal"],
        round(signal["entry"], 1),
    )


def should_send_signal(market, signal):

    key = signal_key(signal)

    previous = last_signals.get(market)

    if previous == key:
        return False

    last_signals[market] = key

    return True


# ============================================================
# CHAT ID
# ============================================================

def get_chat_ids():

    raw = os.getenv(
        "TELEGRAM_CHAT_ID",
        "",
    ).strip()

    if not raw:
        return []

    ids = []

    for item in raw.split(","):

        item = item.strip()

        if not item:
            continue

        try:
            ids.append(int(item))
        except ValueError:
            logger.warning(
                "Invalid TELEGRAM_CHAT_ID: %s",
                item,
            )

    return ids


# ============================================================
# STATUS MESSAGE
# ============================================================

def build_status_message():

    xau = market_status["XAUUSD"]
    nas = market_status["NAS100"]

    xau_status = (
        "🟢 OK"
        if xau["status"] in ("OK", "CACHED")
        else "🔴 ERROR"
    )

    nas_status = (
        "🟢 OK"
        if nas["status"] in ("OK", "CACHED")
        else "🔴 ERROR"
    )

    return (
        f"👑 <b>KING OF XAU/NAS — HEALTH</b>\n\n"
        f"🟢 <b>Scanner:</b> RUNNING\n"
        f"🟢 <b>Market Data:</b> CONNECTED\n"
        f"🟢 <b>Telegram:</b> CONNECTED\n\n"
        f"🟡 <b>XAUUSD:</b> {xau_status}\n"
        f"   Symbol: {xau.get('symbol') or 'N/A'}\n"
        f"   Price: {xau.get('price') or 'N/A'}\n\n"
        f"🔵 <b>NAS100:</b> {nas_status}\n"
        f"   Symbol: {nas.get('symbol') or 'N/A'}\n"
        f"   Price: {nas.get('price') or 'N/A'}\n\n"
        f"⏱️ <b>Last scan:</b> "
        f"{last_scan_time or 'Not yet'}\n"
    )


# ============================================================
# COMMANDS
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "👑 <b>KING OF XAU/NAS</b>\n\n"
        "Professional market scanner is online.\n\n"
        "🟡 XAUUSD\n"
        "🔵 NAS100\n\n"
        "Commands:\n"
        "/status — Bot health\n"
        "/scan — Run a manual scan\n"
        "/watchlist — Show markets\n"
        "/help — Show commands"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = (
        "👑 <b>KING OF XAU/NAS</b>\n\n"
        "/start — Start bot\n"
        "/status — Health status\n"
        "/scan — Scan markets now\n"
        "/watchlist — Show markets\n"
        "/help — Help"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        build_status_message(),
        parse_mode=ParseMode.HTML,
    )


async def watchlist_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        (
            "👑 <b>WATCHLIST</b>\n\n"
            "🟡 XAU/USD\n"
            "🔵 NAS100\n\n"
            f"⏱️ Main timeframe: "
            f"{MAIN_INTERVAL}"
        ),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# SCANNER
# ============================================================

async def perform_scan(bot):

    global last_scan_time

    if not scanner_lock.acquire(blocking=False):

        logger.warning(
            "Scanner already running."
        )

        return

    try:

        last_scan_time = datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

        logger.info(
            "========== MARKET SCAN =========="
        )

        chat_ids = get_chat_ids()

        # ----------------------------------------------------
        # XAU
        # ----------------------------------------------------

        try:

            xau_symbol, xau_df = find_working_symbol(
                XAU_SYMBOLS,
                "XAUUSD",
            )

            if xau_symbol and xau_df is not None:

                xau_signal = analyze_market(
                    xau_df,
                    xau_symbol,
                )

                if xau_signal["signal"] != "NONE":

                    htf = get_htf_bias(
                        xau_symbol
                    )

                    if (
                        xau_signal["signal"] == "BUY"
                        and htf == "BEARISH"
                    ):
                        logger.info(
                            "XAU BUY rejected by HTF."
                        )

                    elif (
                        xau_signal["signal"] == "SELL"
                        and htf == "BULLISH"
                    ):
                        logger.info(
                            "XAU SELL rejected by HTF."
                        )

                    elif should_send_signal(
                        "XAUUSD",
                        xau_signal,
                    ):

                        message = build_signal_message(
                            xau_signal,
                            "XAUUSD",
                        )

                        for chat_id in chat_ids:
                            await safe_send(
                                bot,
                                chat_id,
                                message,
                            )

        except Exception as exc:

            logger.exception(
                "XAU scan failed: %s",
                exc,
            )

            # Important:
            # XAU failure must NOT stop NAS.

        # ----------------------------------------------------
        # NAS100
        # ----------------------------------------------------

        try:

            nas_symbol, nas_df = find_working_symbol(
                NAS_SYMBOLS,
                "NAS100",
            )

            if nas_symbol and nas_df is not None:

                nas_signal = analyze_market(
                    nas_df,
                    nas_symbol,
                )

                if nas_signal["signal"] != "NONE":

                    htf = get_htf_bias(
                        nas_symbol
                    )

                    if (
                        nas_signal["signal"] == "BUY"
                        and htf == "BEARISH"
                    ):
                        logger.info(
                            "NAS BUY rejected by HTF."
                        )

                    elif (
                        nas_signal["signal"] == "SELL"
                        and htf == "BULLISH"
                    ):
                        logger.info(
                            "NAS SELL rejected by HTF."
                        )

                    elif should_send_signal(
                        "NAS100",
                        nas_signal,
                    ):

                        message = build_signal_message(
                            nas_signal,
                            "NAS100",
                        )

                        for chat_id in chat_ids:
                            await safe_send(
                                bot,
                                chat_id,
                                message,
                            )

        except Exception as exc:

            logger.exception(
                "NAS100 scan failed: %s",
                exc,
            )

        logger.info(
            "========== SCAN COMPLETE =========="
        )

    finally:

        scanner_lock.release()


async def scheduled_scan(
    context: ContextTypes.DEFAULT_TYPE,
):

    try:

        await perform_scan(
            context.bot
        )

    except Exception as exc:

        logger.exception(
            "Scheduled scanner error: %s",
            exc,
        )


async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "🔎 <b>Scanning XAUUSD + NAS100...</b>",
        parse_mode=ParseMode.HTML,
    )

    await perform_scan(
        context.bot
    )

    await update.message.reply_text(
        "✅ <b>Scan complete.</b>\n\n"
        "Use /status to check market connectivity.",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# START BOT
# ============================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured"
        )

    if not TWELVE_DATA_API_KEY:

        raise RuntimeError(
            "TWELVE_DATA_API_KEY is not configured"
        )

    # --------------------------------------------------------
    # Flask health server
    # --------------------------------------------------------

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )

    flask_thread.start()

    logger.info(
        "Render health server started on port %s",
        PORT,
    )

    # --------------------------------------------------------
    # Telegram application
    # --------------------------------------------------------

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
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
            "help",
            help_command,
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

    # --------------------------------------------------------
    # Automatic scanner
    # --------------------------------------------------------

    application.job_queue.run_repeating(
        scheduled_scan,
        interval=SCAN_INTERVAL_SECONDS,
        first=10,
    )

    logger.info(
        "======================================"
    )

    logger.info(
        "👑 KING OF XAU/NAS STARTING"
    )

    logger.info(
        "XAU symbols: %s",
        XAU_SYMBOLS,
    )

    logger.info(
        "NAS fallback symbols: %s",
        NAS_SYMBOLS,
    )

    logger.info(
        "Scan interval: %s seconds",
        SCAN_INTERVAL_SECONDS,
    )

    logger.info(
        "======================================"
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":

    main()
