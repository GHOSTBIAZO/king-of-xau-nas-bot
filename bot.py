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
# STRICT GOLD SIGNAL ENGINE
# ============================================================

BOT_NAME = "👑 KING OF XAU_NAS — GOLD"

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TWELVE_DATA_API_KEY = os.getenv(
    "TWELVE_DATA_API_KEY", ""
).strip()

PORT = int(os.getenv("PORT", "10000"))

# ============================================================
# MARKET SETTINGS
# ============================================================

XAU_SYMBOL = "XAU/USD"
INTERVAL = "15min"
OUTPUT_SIZE = 100

# Scan every 10 minutes
SCAN_INTERVAL_SECONDS = 600

# ============================================================
# STORAGE
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
# GLOBAL STATE
# ============================================================

telegram_application = None
chat_id_lock = Lock()

last_signal_key = None
last_signal_time = 0

scanner_running = False


# ============================================================
# FLASK SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return """
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
            <h1>👑 KING OF XAU_NAS — GOLD</h1>
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
        logger.error(f"Flask error: {e}")


# ============================================================
# CHAT ID STORAGE
# ============================================================

def load_chat_id():
    try:
        if not os.path.exists(CHAT_ID_FILE):
            return None

        with open(
            CHAT_ID_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        chat_id = data.get("chat_id")

        if chat_id:
            return str(chat_id)

    except Exception as e:
        logger.error(f"Chat ID load error: {e}")

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
                        "chat_id": str(chat_id),
                        "saved_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    },
                    file,
                    indent=4,
                )

        logger.info(
            "Telegram Chat ID saved automatically."
        )

        return True

    except Exception as e:
        logger.error(
            f"Chat ID save error: {e}"
        )
        return False


# ============================================================
# SEND TELEGRAM MESSAGE
# ============================================================

async def send_message(message):
    global telegram_application

    chat_id = load_chat_id()

    if not chat_id:
        logger.warning(
            "No Telegram Chat ID saved. "
            "Send /start first."
        )
        return False

    if telegram_application is None:
        logger.warning(
            "Telegram application is not ready."
        )
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
            f"Telegram send error: {e}"
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

    saved = save_chat_id(chat_id)

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
            "Use /scan to request a live GOLD scan.\n"
            "Use /status to check the bot."
        )
    else:
        message = (
            "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"
            "⚠️ Chat ID was detected but could "
            "not be saved.\n\n"
            f"🆔 Chat ID: `{chat_id}`"
        )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
    )


# ============================================================
# /STATUS
# ============================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    chat_id = load_chat_id()

    telegram_status = (
        "🟢 CONNECTED"
        if chat_id
        else "🔴 NOT CONNECTED"
    )

    data_status = (
        "🟢 CONNECTED"
        if TWELVE_DATA_API_KEY
        else "🔴 MISSING"
    )

    scanner_status = (
        "🟢 ON"
        if scanner_running
        else "🔴 OFF"
    )

    message = (
        "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 *SYSTEM STATUS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Telegram: {telegram_status}\n"
        f"Twelve Data: {data_status}\n"
        f"Market: 🟡 XAU/USD\n"
        f"Timeframe: {INTERVAL}\n"
        f"Scanner: {scanner_status}\n"
        "Signal Engine: 🧠 STRICT\n"
        "RSI Protection: 🛡️ ON\n"
        "Overextension Filter: 🛡️ ON\n"
    )

    if chat_id:
        message += (
            f"\n🆔 Saved Chat ID: `{chat_id}`\n"
        )
    else:
        message += (
            "\nSend /start to register your Telegram Chat ID.\n"
        )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
    )


# ============================================================
# TWELVE DATA
# ============================================================

def get_gold_data():
    if not TWELVE_DATA_API_KEY:
        logger.error(
            "TWELVE_DATA_API_KEY is missing."
        )
        return None

    url = (
        "https://api.twelvedata.com/"
        "time_series"
    )

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
            timeout=30,
        )

        if response.status_code != 200:
            logger.error(
                f"Twelve Data HTTP error: "
                f"{response.status_code}"
            )
            return None

        data = response.json()

        if "values" not in data:
            logger.error(
                f"Twelve Data error: {data}"
            )
            return None

        values = list(
            reversed(data["values"])
        )

        candles = []

        for item in values:
            try:
                candles.append(
                    {
                        "datetime": item["datetime"],
                        "open": float(item["open"]),
                        "high": float(item["high"]),
                        "low": float(item["low"]),
                        "close": float(item["close"]),
                    }
                )
            except Exception:
                continue

        if len(candles) < 60:
            logger.error(
                "Not enough GOLD candles."
            )
            return None

        return candles

    except Exception as e:
        logger.error(
            f"Gold data error: {e}"
        )
        return None


# ============================================================
# EMA
# ============================================================

def calculate_ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(
        values[:period]
    ) / period

    for price in values[period:]:
        ema = (
            (price - ema)
            * multiplier
        ) + ema

    return ema


# ============================================================
# RSI
# ============================================================

def calculate_rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = (
            values[i]
            - values[i - 1]
        )

        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(period, len(gains)):
        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    candles,
    period=14,
):
    if len(candles) < period + 1:
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
            abs(
                high
                - previous_close
            ),
            abs(
                low
                - previous_close
            ),
        )

        true_ranges.append(tr)

    atr = (
        sum(true_ranges[:period])
        / period
    )

    for tr in true_ranges[period:]:
        atr = (
            (
                atr
                * (period - 1)
            )
            + tr
        ) / period

    return atr


# ============================================================
# CANDLE MOMENTUM
# ============================================================

def candle_momentum(candles):
    if len(candles) < 5:
        return "NEUTRAL"

    current = candles[-1]
    previous = candles[-2]

    body = abs(
        current["close"]
        - current["open"]
    )

    candle_range = (
        current["high"]
        - current["low"]
    )

    if candle_range <= 0:
        return "NEUTRAL"

    body_ratio = (
        body / candle_range
    )

    if (
        current["close"]
        > current["open"]
        and current["close"]
        > previous["close"]
        and body_ratio >= 0.50
    ):
        return "BULLISH"

    if (
        current["close"]
        < current["open"]
        and current["close"]
        < previous["close"]
        and body_ratio >= 0.50
    ):
        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_gold(candles):
    closes = [
        candle["close"]
        for candle in candles
    ]

    highs = [
        candle["high"]
        for candle in candles
    ]

    lows = [
        candle["low"]
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

    if any(
        value is None
        for value in (
            ema20,
            ema50,
            rsi,
            atr,
        )
    ):
        return None

    momentum = candle_momentum(
        candles
    )

    recent_high = max(
        highs[-20:]
    )

    recent_low = min(
        lows[-20:]
    )

    # ========================================================
    # TREND
    # ========================================================

    if (
        price > ema20
        and ema20 > ema50
    ):
        trend = "BULLISH 📈"

    elif (
        price < ema20
        and ema20 < ema50
    ):
        trend = "BEARISH 📉"

    else:
        trend = "RANGING ↔️"

    # ========================================================
    # ATR DISTANCE FROM EMA20
    # ========================================================

    atr_distance = (
        abs(price - ema20) / atr
        if atr > 0
        else 0
    )

    overextended_up = (
        price > ema20
        and atr_distance >= 2.5
    )

    overextended_down = (
        price < ema20
        and atr_distance >= 2.5
    )

    # ========================================================
    # SCORE
    # ========================================================

    buy_score = 0
    sell_score = 0

    reasons = []

    # Trend

    if price > ema20:
        buy_score += 20

    if price > ema50:
        buy_score += 15

    if ema20 > ema50:
        buy_score += 15

    if price < ema20:
        sell_score += 20

    if price < ema50:
        sell_score += 15

    if ema20 < ema50:
        sell_score += 15

    # ========================================================
    # RSI FILTER
    # ========================================================

    if 50 <= rsi < 65:
        buy_score += 15
        reasons.append(
            "RSI supports bullish momentum"
        )

    elif 65 <= rsi < 72:
        buy_score += 5
        reasons.append(
            "RSI elevated"
        )

    elif rsi >= 72:
        buy_score -= 15
        reasons.append(
            "RSI overbought"
        )

    if 35 < rsi <= 50:
        sell_score += 15
        reasons.append(
            "RSI supports bearish momentum"
        )

    elif 28 < rsi <= 35:
        sell_score += 5
        reasons.append(
            "RSI low"
        )

    elif rsi <= 28:
        sell_score -= 15
        reasons.append(
            "RSI oversold"
        )

    # ========================================================
    # CANDLE MOMENTUM
    # ========================================================

    if momentum == "BULLISH":
        buy_score += 10

    elif momentum == "BEARISH":
        sell_score += 10

    # ========================================================
    # OVEREXTENSION
    # ========================================================

    if overextended_up:
        buy_score -= 20
        reasons.append(
            "Price is extended above EMA20"
        )

    if overextended_down:
        sell_score -= 20
        reasons.append(
            "Price is extended below EMA20"
        )

    # Extreme conditions

    if rsi >= 75 and overextended_up:
        buy_score -= 20
        reasons.append(
            "Extreme overbought + extension"
        )

    if rsi <= 25 and overextended_down:
        sell_score -= 20
        reasons.append(
            "Extreme oversold + extension"
        )

    # ========================================================
    # STRUCTURE
    # ========================================================

    if price >= recent_high * 0.998:
        buy_score += 5

    if price <= recent_low * 1.002:
        sell_score += 5

    # ========================================================
    # DIRECTION
    # ========================================================

    if buy_score > sell_score:
        direction = "BUY"
        raw_score = buy_score

    elif sell_score > buy_score:
        direction = "SELL"
        raw_score = sell_score

    else:
        direction = "WAIT"
        raw_score = 50

    # ========================================================
    # HARD SAFETY FILTER
    # ========================================================

    wait_reason = ""

    if (
        rsi >= 75
        and price > ema20
    ):
        direction = "WAIT"
        wait_reason = (
            "RSI is extremely overbought"
        )

    elif (
        rsi <= 25
        and price < ema20
    ):
        direction = "WAIT"
        wait_reason = (
            "RSI is extremely oversold"
        )

    elif overextended_up:
        direction = "WAIT"
        wait_reason = (
            "Price is too far above EMA20"
        )

    elif overextended_down:
        direction = "WAIT"
        wait_reason = (
            "Price is too far below EMA20"
        )

    elif trend == "RANGING":
        direction = "WAIT"
        wait_reason = (
            "Market structure is ranging"
        )

    # ========================================================
    # CONFIDENCE
    # ========================================================

    if direction == "WAIT":
        confidence = 50
    else:
        confidence = min(
            max(raw_score, 50),
            95,
        )

    # ========================================================
    # SIGNAL NAME
    # ========================================================

    if direction == "BUY":

        if confidence >= 80:
            signal = "STRONG BUY 🟢🟢"
        else:
            signal = "BUY 🟢"

    elif direction == "SELL":

        if confidence >= 80:
            signal = "STRONG SELL 🔴🔴"
        else:
            signal = "SELL 🔴"

    else:
        signal = "WAIT / PULLBACK 🟡"

    # ========================================================
    # TRADE LEVELS
    # ========================================================

    if direction == "BUY":

        entry = price

        stop_loss = (
            price - atr * 1.5
        )

        tp1 = (
            price + atr
        )

        tp2 = (
            price + atr * 2
        )

        tp3 = (
            price + atr * 3
        )

        pending_type = "BUY LIMIT"

        pending_entry = (
            price - atr * 0.50
        )

    elif direction == "SELL":

        entry = price

        stop_loss = (
            price + atr * 1.5
        )

        tp1 = (
            price - atr
        )

        tp2 = (
            price - atr * 2
        )

        tp3 = (
            price - atr * 3
        )

        pending_type = "SELL LIMIT"

        pending_entry = (
            price + atr * 0.50
        )

    else:

        entry = price
        stop_loss = None
        tp1 = None
        tp2 = None
        tp3 = None

        if trend == "BULLISH 📈":

            pending_type = "BUY LIMIT WATCH"

            pending_entry = (
                price - atr * 0.50
            )

        elif trend == "BEARISH 📉":

            pending_type = "SELL LIMIT WATCH"

            pending_entry = (
                price + atr * 0.50
            )

        else:

            pending_type = "NO ENTRY"

            pending_entry = None

    return {
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "trend": trend,
        "momentum": momentum,
        "atr_distance": atr_distance,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "direction": direction,
        "signal": signal,
        "confidence": confidence,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "pending_type": pending_type,
        "pending_entry": pending_entry,
        "wait_reason": wait_reason,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "reasons": reasons,
    }


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(analysis):

    direction = analysis["direction"]

    message = (
        "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"
        "🟡 *XAU/USD*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🧠 *AI MARKET SIGNAL*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Signal: *{analysis['signal']}*\n"
        f"🎯 Confidence: "
        f"*{analysis['confidence']:.0f}%*\n\n"
        f"💰 Price: "
        f"`${analysis['price']:,.2f}`\n"
        f"📈 Trend: "
        f"*{analysis['trend']}*\n"
        f"⚡ Momentum: "
        f"*{analysis['momentum']}*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *TECHNICAL ANALYSIS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"EMA 20: "
        f"`{analysis['ema20']:,.2f}`\n"
        f"EMA 50: "
        f"`{analysis['ema50']:,.2f}`\n"
        f"RSI 14: "
        f"`{analysis['rsi']:.1f}`\n"
        f"ATR 14: "
        f"`{analysis['atr']:.2f}`\n"
        f"Distance from EMA20: "
        f"`{analysis['atr_distance']:.2f} ATR`\n\n"
    )

    # ========================================================
    # WAIT
    # ========================================================

    if direction == "WAIT":

        message += (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🟡 *ACTION: WAIT / PULLBACK*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚠️ {analysis['wait_reason']}\n\n"
            "🚫 *Do not chase the current price.*\n"
            "Wait for a pullback or fresh confirmation.\n\n"
        )

        if analysis["pending_entry"] is not None:

            message += (
                f"⏳ Watch level: "
                f"`{analysis['pending_entry']:,.2f}`\n\n"
            )

    else:

        message += (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🎯 *TRADE LEVELS*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 Entry: "
            f"`${analysis['entry']:,.2f}`\n"
            f"🛑 Stop Loss: "
            f"`${analysis['stop_loss']:,.2f}`\n"
            f"🥇 TP1: "
            f"`${analysis['tp1']:,.2f}`\n"
            f"🥈 TP2: "
            f"`${analysis['tp2']:,.2f}`\n"
            f"🏆 TP3: "
            f"`${analysis['tp3']:,.2f}`\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⏳ *PENDING ORDER IDEA*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{analysis['pending_type']}: "
            f"`{analysis['pending_entry']:,.2f}`\n\n"
        )

    # ========================================================
    # ENGINE NOTES
    # ========================================================

    if analysis["reasons"]:

        message += (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🧠 *ENGINE NOTES*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        used = []

        for reason in analysis["reasons"]:

            if reason not in used:

                used.append(reason)

        for reason in used[:6]:

            message += (
                f"• {reason}\n"
            )

        message += "\n"

    message += (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ *SYSTEM*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏱ Timeframe: *{INTERVAL}*\n"
        "📡 Data: *Twelve Data*\n"
        "🧠 Engine: *STRICT*\n"
        "🛡️ RSI Protection: *ON*\n"
        "🛡️ Overextension Filter: *ON*\n"
        "🤖 Automatic Scanner: *ON*\n\n"
        "⚠️ Market information is for analysis only.\n"
        "Not financial advice. Manage risk carefully."
    )

    return message


# ============================================================
# GOLD SCAN
# ============================================================

def scan_gold():

    logger.info(
        "🔎 Scanning XAU/USD..."
    )

    candles = get_gold_data()

    if not candles:
        return None

    analysis = analyze_gold(
        candles
    )

    if not analysis:
        return None

    logger.info(
        f"Signal: {analysis['signal']} | "
        f"Price: {analysis['price']:.2f} | "
        f"RSI: {analysis['rsi']:.1f} | "
        f"Confidence: "
        f"{analysis['confidence']:.0f}%"
    )

    return analysis


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

    analysis = await asyncio.to_thread(
        scan_gold
    )

    if not analysis:

        await update.message.reply_text(
            "❌ GOLD data could not be retrieved.\n\n"
            "Check your Twelve Data API key."
        )

        return

    message = format_signal(
        analysis
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
    )


# ============================================================
# AUTOMATIC SCANNER
# ============================================================

async def automatic_scanner():

    global scanner_running
    global last_signal_key
    global last_signal_time

    scanner_running = True

    logger.info(
        "🟢 Automatic GOLD scanner started."
    )

    while True:

        try:

            analysis = await asyncio.to_thread(
                scan_gold
            )

            if analysis:

                direction = analysis[
                    "direction"
                ]

                price = analysis[
                    "price"
                ]

                reason = analysis[
                    "wait_reason"
                ]

                price_zone = round(
                    price,
                    1,
                )

                signal_key = (
                    f"{direction}_"
                    f"{reason}_"
                    f"{price_zone}"
                )

                now = time.time()

                should_send = False

                if last_signal_key is None:

                    should_send = True

                elif (
                    signal_key
                    != last_signal_key
                ):

                    should_send = True

                elif (
                    now
                    - last_signal_time
                    >= 1800
                ):

                    should_send = True

                if should_send:

                    message = format_signal(
                        analysis
                    )

                    sent = await send_message(
                        message
                    )

                    if sent:

                        last_signal_key = (
                            signal_key
                        )

                        last_signal_time = now

                        logger.info(
                            "📨 GOLD signal sent."
                        )

        except Exception as e:

            logger.exception(
                f"Scanner error: {e}"
            )

        await asyncio.sleep(
            SCAN_INTERVAL_SECONDS
        )


# ============================================================
# START SCANNER THREAD
# ============================================================

def start_scanner_thread():

    def runner():

        try:

            asyncio.run(
                automatic_scanner()
            )

        except Exception as e:

            logger.exception(
                f"Scanner stopped: {e}"
            )

    thread = Thread(
        target=runner,
        daemon=True,
    )

    thread.start()

    logger.info(
        "🟢 Scanner background thread launched."
    )


# ============================================================
# TELEGRAM INITIALIZATION
# ============================================================

async def post_init(
    application: Application,
):

    global telegram_application

    telegram_application = application

    chat_id = load_chat_id()

    if chat_id:

        logger.info(
            "Saved Telegram Chat ID loaded."
        )

    else:

        logger.warning(
            "No Chat ID saved. "
            "Send /start in Telegram."
        )


def create_application():

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    application = (
        Application.builder()
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
            "scan",
            scan_command,
        )
    )

    return application


# ============================================================
# MAIN
# ============================================================

def main():

    global telegram_application

    logger.info(
        "===================================="
    )

    logger.info(
        "👑 KING OF XAU_NAS — GOLD"
    )

    logger.info(
        "🟢 Starting bot..."
    )

    logger.info(
        f"Market: {XAU_SYMBOL}"
    )

    logger.info(
        f"Timeframe: {INTERVAL}"
    )

    logger.info(
        "🧠 Strict signal engine: ON"
    )

    logger.info(
        "🛡️ RSI protection: ON"
    )

    logger.info(
        "🛡️ Overextension protection: ON"
    )

    if not TELEGRAM_BOT_TOKEN:

        logger.error(
            "❌ TELEGRAM_BOT_TOKEN is missing."
        )

        return

    if not TWELVE_DATA_API_KEY:

        logger.error(
            "❌ TWELVE_DATA_API_KEY is missing."
        )

        return

    # ========================================================
    # FLASK
    # ========================================================

    flask_thread = Thread(
        target=run_flask,
        daemon=True,
    )

    flask_thread.start()

    logger.info(
        "🟢 Flask server started."
    )

    # ========================================================
    # TELEGRAM
    # ========================================================

    telegram_application = (
        create_application()
    )

    # ========================================================
    # SCANNER
    # ========================================================

    start_scanner_thread()

    logger.info(
        "===================================="
    )

    logger.info(
        "👑 KING OF XAU_NAS ONLINE"
    )

    logger.info(
        "🟢 Telegram: ONLINE"
    )

    logger.info(
        "🟡 XAU/USD: ONLINE"
    )

    logger.info(
        "🧠 Signal engine: STRICT"
    )

    logger.info(
        "===================================="
    )

    telegram_application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
