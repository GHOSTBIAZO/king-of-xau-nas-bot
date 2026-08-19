import os
import asyncio
import logging
import threading
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
# 👑 KING OF XAU_NAS — INSTITUTIONAL GOLD TELEGRAM AI
# ============================================================

BOT_NAME = "👑 KING OF XAU_NAS — GOLD"

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

# Optional:
# Put your Telegram chat ID in Render if you want the bot
# to automatically send signals to one specific chat.
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

PORT = int(os.getenv("PORT", "10000"))


# ============================================================
# MARKET SETTINGS
# ============================================================

XAU_SYMBOL = "XAU/USD"

INTERVAL = "15min"
OUTPUT_SIZE = 120

SCAN_SECONDS = 60

# Signal quality
MIN_CONFIDENCE = 70

# ATR multipliers
SL_ATR_MULTIPLIER = 1.5

TP1_ATR_MULTIPLIER = 1.5
TP2_ATR_MULTIPLIER = 2.5
TP3_ATR_MULTIPLIER = 4.0


# ============================================================
# GLOBAL STATE
# ============================================================

last_signal_key = None

active_trade = None

bot_application = None

stop_event = threading.Event()


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(BOT_NAME)


# ============================================================
# FLASK SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "KING OF XAU_NAS — GOLD BOT ONLINE 👑", 200


@app.route("/health")
def health():
    return {
        "status": "online",
        "bot": BOT_NAME,
        "symbol": XAU_SYMBOL,
        "timeframe": INTERVAL,
    }, 200


def run_flask():
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

async def send_chat_message(
    context,
    message,
    chat_id=None,
):
    """
    Send Telegram message.

    If chat_id is supplied, send there.
    Otherwise use TELEGRAM_CHAT_ID.
    """

    target_chat_id = chat_id or TELEGRAM_CHAT_ID

    if not target_chat_id:
        logger.warning(
            "No TELEGRAM_CHAT_ID configured."
        )
        return False

    try:
        await context.bot.send_message(
            chat_id=target_chat_id,
            text=message,
            parse_mode="Markdown",
        )

        return True

    except Exception as e:
        logger.error(
            "Telegram send error: %s",
            e,
        )

        return False


# ============================================================
# TWELVE DATA
# ============================================================

def get_gold_data():
    """
    Download XAU/USD candles from Twelve Data.
    """

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
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

        if "status" in data:
            if data["status"] == "error":
                logger.error(
                    "Twelve Data error: %s",
                    data.get("message"),
                )
                return None

        values = data.get("values")

        if not values:
            logger.error(
                "No XAU/USD data returned."
            )
            return None

        # Twelve Data returns newest first.
        values = list(reversed(values))

        candles = []

        for candle in values:

            try:

                candles.append(
                    {
                        "datetime": candle["datetime"],
                        "open": float(candle["open"]),
                        "high": float(candle["high"]),
                        "low": float(candle["low"]),
                        "close": float(candle["close"]),
                    }
                )

            except (KeyError, ValueError, TypeError):
                continue

        if len(candles) < 60:
            logger.warning(
                "Not enough candles: %s",
                len(candles),
            )
            return None

        return candles

    except requests.RequestException as e:

        logger.error(
            "Market data request failed: %s",
            e,
        )

        return None

    except Exception as e:

        logger.exception(
            "Unexpected market data error: %s",
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

    if len(values) <= period:
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

    average_gain = sum(
        gains[:period]
    ) / period

    average_loss = sum(
        losses[:period]
    ) / period

    for i in range(
        period,
        len(gains),
    ):

        average_gain = (
            (average_gain * (period - 1))
            + gains[i]
        ) / period

        average_loss = (
            (average_loss * (period - 1))
            + losses[i]
        ) / period

    if average_loss == 0:
        return 100.0

    rs = average_gain / average_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):

    if len(candles) <= period:
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
# MARKET STRUCTURE
# ============================================================

def market_structure(candles):

    if len(candles) < 10:
        return "NEUTRAL"

    recent = candles[-10:]

    highs = [
        candle["high"]
        for candle in recent
    ]

    lows = [
        candle["low"]
        for candle in recent
    ]

    if highs[-1] > highs[-3] and lows[-1] > lows[-3]:
        return "BULLISH"

    if highs[-1] < highs[-3] and lows[-1] < lows[-3]:
        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# SIGNAL ENGINE
# ============================================================

def generate_signal(candles):

    closes = [
        candle["close"]
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

    structure = market_structure(
        candles
    )

    if (
        ema20 is None
        or ema50 is None
        or rsi is None
        or atr is None
    ):
        return None

    bullish_points = 0
    bearish_points = 0

    # ========================================================
    # EMA TREND
    # ========================================================

    if ema20 > ema50:
        bullish_points += 30

    elif ema20 < ema50:
        bearish_points += 30

    # ========================================================
    # PRICE VS EMA
    # ========================================================

    if price > ema20:
        bullish_points += 20

    elif price < ema20:
        bearish_points += 20

    # ========================================================
    # RSI
    # ========================================================

    if 50 <= rsi <= 70:
        bullish_points += 20

    elif 30 <= rsi < 50:
        bearish_points += 20

    elif rsi > 70:
        bullish_points += 10

    elif rsi < 30:
        bearish_points += 10

    # ========================================================
    # MARKET STRUCTURE
    # ========================================================

    if structure == "BULLISH":
        bullish_points += 30

    elif structure == "BEARISH":
        bearish_points += 30

    # ========================================================
    # DETERMINE SIGNAL
    # ========================================================

    if bullish_points > bearish_points:

        side = "BUY"

        confidence = bullish_points

    elif bearish_points > bullish_points:

        side = "SELL"

        confidence = bearish_points

    else:

        return {
            "signal": "WAIT",
            "confidence": 50,
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi,
            "atr": atr,
            "structure": structure,
        }

    # ========================================================
    # FILTER WEAK SIGNALS
    # ========================================================

    if confidence < MIN_CONFIDENCE:

        return {
            "signal": "WAIT",
            "confidence": confidence,
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi,
            "atr": atr,
            "structure": structure,
        }

    # ========================================================
    # TRADE LEVELS
    # ========================================================

    if side == "BUY":

        entry = price

        sl = (
            entry
            - (
                atr
                * SL_ATR_MULTIPLIER
            )
        )

        tp1 = (
            entry
            + (
                atr
                * TP1_ATR_MULTIPLIER
            )
        )

        tp2 = (
            entry
            + (
                atr
                * TP2_ATR_MULTIPLIER
            )
        )

        tp3 = (
            entry
            + (
                atr
                * TP3_ATR_MULTIPLIER
            )
        )

        pending_type = "BUY STOP / MARKET BUY"

    else:

        entry = price

        sl = (
            entry
            + (
                atr
                * SL_ATR_MULTIPLIER
            )
        )

        tp1 = (
            entry
            - (
                atr
                * TP1_ATR_MULTIPLIER
            )
        )

        tp2 = (
            entry
            - (
                atr
                * TP2_ATR_MULTIPLIER
            )
        )

        tp3 = (
            entry
            - (
                atr
                * TP3_ATR_MULTIPLIER
            )
        )

        pending_type = "SELL STOP / MARKET SELL"

    return {
        "signal": side,
        "confidence": confidence,
        "price": price,
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
        "order_type": pending_type,
    }


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(signal):

    side = signal["signal"]

    if side == "BUY":
        emoji = "🟢"
    else:
        emoji = "🔴"

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = (
        "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"

        "🟡 *XAU/USD*\n"
        f"{emoji} *SIGNAL: {side}*\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 *AI MARKET ANALYSIS*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"📊 Structure: "
        f"*{signal['structure']}*\n"

        f"🎯 Confidence: "
        f"*{signal['confidence']}%*\n\n"

        f"💰 Entry: "
        f"`${signal['entry']:,.2f}`\n"

        f"🛑 Stop Loss: "
        f"`${signal['sl']:,.2f}`\n\n"

        f"🎯 TP1: "
        f"`${signal['tp1']:,.2f}`\n"

        f"🎯 TP2: "
        f"`${signal['tp2']:,.2f}`\n"

        f"🏆 TP3: "
        f"`${signal['tp3']:,.2f}`\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "📈 *TECHNICAL DATA*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"EMA 20: "
        f"`{signal['ema20']:,.2f}`\n"

        f"EMA 50: "
        f"`{signal['ema50']:,.2f}`\n"

        f"RSI 14: "
        f"`{signal['rsi']:.1f}`\n"

        f"ATR 14: "
        f"`{signal['atr']:.2f}`\n\n"

        f"⏱ Timeframe: *{INTERVAL}*\n"

        f"📌 Order Type: "
        f"*{signal['order_type']}*\n\n"

        f"🕐 {now}\n\n"

        "⚠️ *Market information is for "
        "analysis only. Not financial advice.*"
    )

    return message


# ============================================================
# WAIT MESSAGE
# ============================================================

def format_wait(signal):

    return (
        "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"
        "🟡 *XAU/USD*\n\n"
        "⏳ *WAIT — NO HIGH QUALITY SETUP*\n\n"
        f"💰 Price: "
        f"`${signal['price']:,.2f}`\n\n"

        f"📈 Structure: "
        f"*{signal['structure']}*\n"

        f"🎯 Confidence: "
        f"*{signal['confidence']}%*\n\n"

        f"EMA 20: "
        f"`{signal['ema20']:,.2f}`\n"

        f"EMA 50: "
        f"`{signal['ema50']:,.2f}`\n"

        f"RSI 14: "
        f"`{signal['rsi']:.1f}`\n"

        f"ATR 14: "
        f"`{signal['atr']:.2f}`\n\n"

        "🤖 *AI is monitoring the market.*"
    )


# ============================================================
# TRADE MONITOR
# ============================================================

async def monitor_trade(
    context,
    price,
):

    global active_trade

    if not active_trade:
        return

    trade = active_trade

    side = trade["signal"]

    # ========================================================
    # BUY
    # ========================================================

    if side == "BUY":

        if not trade["tp1_hit"] and price >= trade["tp1"]:

            trade["tp1_hit"] = True

            await send_chat_message(
                context,
                (
                    "👑 *TP1 HIT* 🎯\n\n"
                    "🟡 XAU/USD\n"
                    "🟢 BUY\n\n"
                    f"💰 Price: `${price:,.2f}`\n\n"
                    "🔒 TP1 reached.\n"
                    "📈 Trade continues toward TP2."
                ),
            )

        if not trade["tp2_hit"] and price >= trade["tp2"]:

            trade["tp2_hit"] = True

            await send_chat_message(
                context,
                (
                    "👑 *TP2 HIT* 🎯🎯\n\n"
                    "🟡 XAU/USD\n"
                    "🟢 BUY\n\n"
                    f"💰 Price: `${price:,.2f}`\n\n"
                    "🏆 TP2 reached.\n"
                    "🚀 Final target: TP3."
                ),
            )

        if not trade["tp3_hit"] and price >= trade["tp3"]:

            trade["tp3_hit"] = True

            await send_chat_message(
                context,
                (
                    "👑 *TP3 HIT — "
                    "TRADE COMPLETE* 🏆\n\n"

                    "🟡 XAU/USD\n"
                    "🟢 BUY\n\n"

                    f"💰 Exit: `${price:,.2f}`\n\n"

                    "🏆 *Full target reached.*\n"
                    "✅ Trade completed."
                ),
            )

            active_trade = None

            return

        if price <= trade["sl"]:

            await send_chat_message(
                context,
                (
                    "🛑 *STOP LOSS HIT*\n\n"
                    "🟡 XAU/USD\n"
                    "🟢 BUY\n\n"

                    f"💰 Exit: `${price:,.2f}`\n\n"

                    "❌ Trade closed at SL."
                ),
            )

            active_trade = None

            return

    # ========================================================
    # SELL
    # ========================================================

    elif side == "SELL":

        if not trade["tp1_hit"] and price <= trade["tp1"]:

            trade["tp1_hit"] = True

            await send_chat_message(
                context,
                (
                    "👑 *TP1 HIT* 🎯\n\n"
                    "🟡 XAU/USD\n"
                    "🔴 SELL\n\n"
                    f"💰 Price: `${price:,.2f}`\n\n"
                    "🔒 TP1 reached.\n"
                    "📉 Trade continues toward TP2."
                ),
            )

        if not trade["tp2_hit"] and price <= trade["tp2"]:

            trade["tp2_hit"] = True

            await send_chat_message(
                context,
                (
                    "👑 *TP2 HIT* 🎯🎯\n\n"
                    "🟡 XAU/USD\n"
                    "🔴 SELL\n\n"
                    f"💰 Price: `${price:,.2f}`\n\n"
                    "🏆 TP2 reached.\n"
                    "🚀 Final target: TP3."
                ),
            )

        if not trade["tp3_hit"] and price <= trade["tp3"]:

            trade["tp3_hit"] = True

            await send_chat_message(
                context,
                (
                    "👑 *TP3 HIT — "
                    "TRADE COMPLETE* 🏆\n\n"

                    "🟡 XAU/USD\n"
                    "🔴 SELL\n\n"

                    f"💰 Exit: `${price:,.2f}`\n\n"

                    "🏆 *Full target reached.*\n"
                    "✅ Trade completed."
                ),
            )

            active_trade = None

            return

        if price >= trade["sl"]:

            await send_chat_message(
                context,
                (
                    "🛑 *STOP LOSS HIT*\n\n"
                    "🟡 XAU/USD\n"
                    "🔴 SELL\n\n"

                    f"💰 Exit: `${price:,.2f}`\n\n"

                    "❌ Trade closed at SL."
                ),
            )

            active_trade = None

            return


# ============================================================
# MARKET SCANNER
# ============================================================

async def scan_market(
    context,
    force=False,
):

    global last_signal_key
    global active_trade

    candles = await asyncio.to_thread(
        get_gold_data
    )

    if not candles:

        logger.warning(
            "Unable to retrieve gold data."
        )

        return

    signal = generate_signal(
        candles
    )

    if not signal:

        logger.warning(
            "Unable to generate signal."
        )

        return

    price = signal["price"]

    # ========================================================
    # MONITOR ACTIVE TRADE
    # ========================================================

    if active_trade:

        await monitor_trade(
            context,
            price,
        )

    # ========================================================
    # WAIT
    # ========================================================

    if signal["signal"] == "WAIT":

        logger.info(
            "WAIT | Price %.2f | Confidence %s%%",
            price,
            signal["confidence"],
        )

        return

    # ========================================================
    # UNIQUE SIGNAL KEY
    # ========================================================

    candle_time = candles[-1]["datetime"]

    signal_key = (
        f"{candle_time}_"
        f"{signal['signal']}"
    )

    # Don't send duplicate signal
    # for the same candle.
    if not force and signal_key == last_signal_key:

        logger.info(
            "Duplicate signal skipped."
        )

        return

    # ========================================================
    # REPLACE ACTIVE TRADE
    # ========================================================

    active_trade = {
        "signal": signal["signal"],
        "entry": signal["entry"],
        "sl": signal["sl"],
        "tp1": signal["tp1"],
        "tp2": signal["tp2"],
        "tp3": signal["tp3"],
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "created_at": candle_time,
    }

    last_signal_key = signal_key

    message = format_signal(
        signal
    )

    await send_chat_message(
        context,
        message,
    )

    logger.info(
        "%s signal sent | Entry %.2f | SL %.2f | TP3 %.2f | Confidence %s%%",
        signal["signal"],
        signal["entry"],
        signal["sl"],
        signal["tp3"],
        signal["confidence"],
    )


# ============================================================
# BACKGROUND MONITOR
# ============================================================

async def background_monitor(
    context,
):

    logger.info(
        "Background gold scanner started."
    )

    while not stop_event.is_set():

        try:

            await scan_market(
                context
            )

        except asyncio.CancelledError:

            logger.info(
                "Background monitor cancelled."
            )

            break

        except Exception as e:

            logger.exception(
                "Monitor error: %s",
                e,
            )

        try:

            await asyncio.sleep(
                SCAN_SECONDS
            )

        except asyncio.CancelledError:

            break


# ============================================================
# /START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    message = (
        "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"

        "🟢 *BOT ONLINE*\n\n"

        "🟡 Market: *XAU/USD*\n"
        f"⏱ Timeframe: *{INTERVAL}*\n"
        "📡 Data: *Twelve Data*\n"
        "🤖 Engine: *AI Technical Scanner*\n\n"

        "The bot is monitoring GOLD for "
        "high-quality BUY and SELL setups.\n\n"

        "Commands:\n"
        "• /start — Start bot\n"
        "• /status — Bot status\n"
        "• /scan — Scan GOLD now\n"
        "• /trade — Current trade\n\n"

        "⚠️ Analysis only. Not financial advice."
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="Markdown",
    )


# ============================================================
# /STATUS
# ============================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    status = (
        "👑 *KING OF XAU_NAS — GOLD*\n\n"
        "🟢 *STATUS: ONLINE*\n\n"
        f"🟡 Symbol: `{XAU_SYMBOL}`\n"
        f"⏱ Timeframe: `{INTERVAL}`\n"
        f"🔄 Scanner: Every `{SCAN_SECONDS}` seconds\n"
        f"🎯 Minimum confidence: `{MIN_CONFIDENCE}%`\n"
        "📡 Data: `Twelve Data`\n"
        "📲 Notifications: `Telegram`\n"
    )

    if active_trade:

        status += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "📊 *ACTIVE SIGNAL*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            f"Direction: "
            f"*{active_trade['signal']}*\n"

            f"Entry: "
            f"`${active_trade['entry']:,.2f}`\n"

            f"SL: "
            f"`${active_trade['sl']:,.2f}`\n"

            f"TP1: "
            f"`${active_trade['tp1']:,.2f}`\n"

            f"TP2: "
            f"`${active_trade['tp2']:,.2f}`\n"

            f"TP3: "
            f"`${active_trade['tp3']:,.2f}`\n"
        )

    else:

        status += (
            "\n📭 *No active trade.*"
        )

    await update.message.reply_text(
        status,
        parse_mode="Markdown",
    )


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

    await scan_market(
        context,
        force=True,
    )


# ============================================================
# /TRADE
# ============================================================

async def trade_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not active_trade:

        await update.message.reply_text(
            "📭 *No active GOLD trade.*",
            parse_mode="Markdown",
        )

        return

    trade = active_trade

    message = (
        "👑 *ACTIVE XAU/USD TRADE* 👑\n\n"

        f"Direction: *{trade['signal']}*\n\n"

        f"Entry: `${trade['entry']:,.2f}`\n"

        f"SL: `${trade['sl']:,.2f}`\n\n"

        f"TP1: `${trade['tp1']:,.2f}`\n"

        f"TP2: `${trade['tp2']:,.2f}`\n"

        f"TP3: `${trade['tp3']:,.2f}`\n\n"

        f"TP1 hit: "
        f"{'✅' if trade['tp1_hit'] else '⏳'}\n"

        f"TP2 hit: "
        f"{'✅' if trade['tp2_hit'] else '⏳'}\n"

        f"TP3 hit: "
        f"{'✅' if trade['tp3_hit'] else '⏳'}"
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
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
        context.error,
    )


# ============================================================
# START TELEGRAM APPLICATION
# ============================================================

async def start_bot():

    global bot_application

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not TWELVE_DATA_API_KEY:

        raise RuntimeError(
            "TWELVE_DATA_API_KEY is missing."
        )

    logger.info(
        "Starting %s",
        BOT_NAME,
    )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    bot_application = application

    # ========================================================
    # COMMANDS
    # ========================================================

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

    application.add_handler(
        CommandHandler(
            "trade",
            trade_command,
        )
    )

    application.add_error_handler(
        error_handler
    )

    # ========================================================
    # START
    # ========================================================

    await application.initialize()

    await application.start()

    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES
    )

    logger.info(
        "Telegram polling started."
    )

    # ========================================================
    # BACKGROUND MARKET SCANNER
    # ========================================================

    monitor_task = asyncio.create_task(
        background_monitor(
            application
        )
    )

    try:

        while not stop_event.is_set():

            await asyncio.sleep(1)

    finally:

        logger.info(
            "Stopping bot..."
        )

        monitor_task.cancel()

        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        await application.updater.stop()

        await application.stop()

        await application.shutdown()

        logger.info(
            "Bot shutdown complete."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    # Flask health server
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
        name="FlaskServer",
    )

    flask_thread.start()

    logger.info(
        "Flask server started on port %s",
        PORT,
    )

    try:

        asyncio.run(
            start_bot()
        )

    except KeyboardInterrupt:

        logger.info(
            "Keyboard interrupt received."
        )

    except Exception as e:

        logger.exception(
            "Fatal error: %s",
            e,
        )

    finally:

        stop_event.set()

        logger.info(
            "KING OF XAU_NAS stopped."
        )


if __name__ == "__main__":
    main()
