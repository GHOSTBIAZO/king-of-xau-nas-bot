import os
import json
import time
import asyncio
import logging
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
# ADVANCED CONFIRMATION ENGINE
# RENDER + TELEGRAM VERSION
# ============================================================

BOT_NAME = "👑 KING OF XAU_NAS — GOLD"

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

# Scan every 5 minutes
SCAN_INTERVAL_SECONDS = 300

# ============================================================
# STORAGE
# ============================================================

CHAT_ID_FILE = "telegram_chat_id.json"

# Runtime Chat ID
# This is updated immediately when /start is used.
TELEGRAM_CHAT_ID = None

# ============================================================
# ALERT STATE
# ============================================================

last_confirmed_key = None
last_confirmed_time = 0

last_setup_key = None
last_setup_stage = None

scanner_running = False

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(BOT_NAME)

# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>King of XAU_NAS</title>
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
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

        <p>🟡 XAU/USD</p>
        <p>⏱ 15 Minute Analysis</p>
        <p>🧠 Advanced Confirmation Engine</p>
        <p>🤖 Automatic Scanner</p>

    </body>
    </html>
    """


@app.route("/health")
def health():
    return {
        "status": "online",
        "bot": BOT_NAME,
        "market": XAU_SYMBOL,
        "timeframe": INTERVAL,
        "scanner": scanner_running,
    }


def run_flask():
    """
    Render requires the application to listen on $PORT.
    """

    try:

        logger.info(
            f"🌐 Starting Flask on port {PORT}"
        )

        app.run(
            host="0.0.0.0",
            port=PORT,
            debug=False,
            use_reloader=False,
        )

    except Exception as e:

        logger.exception(
            f"Flask error: {e}"
        )


# ============================================================
# CHAT ID STORAGE
# ============================================================

def load_chat_id():

    global TELEGRAM_CHAT_ID

    # First use runtime value
    if TELEGRAM_CHAT_ID:

        return str(
            TELEGRAM_CHAT_ID
        )

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

            TELEGRAM_CHAT_ID = str(
                chat_id
            )

            logger.info(
                f"🆔 Chat ID loaded: "
                f"{TELEGRAM_CHAT_ID}"
            )

            return TELEGRAM_CHAT_ID

    except Exception as e:

        logger.error(
            f"Chat ID load error: {e}"
        )

    return None


def save_chat_id(chat_id):

    global TELEGRAM_CHAT_ID

    try:

        TELEGRAM_CHAT_ID = str(
            chat_id
        )

        with open(
            CHAT_ID_FILE,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                {
                    "chat_id":
                        TELEGRAM_CHAT_ID,
                    "saved_at":
                        datetime.now(
                            timezone.utc
                        ).isoformat(),
                },
                file,
                indent=4,
            )

        logger.info(
            f"🆔 Telegram Chat ID saved: "
            f"{TELEGRAM_CHAT_ID}"
        )

        return True

    except Exception as e:

        logger.error(
            f"Chat ID save error: {e}"
        )

        # Runtime ID is still retained
        TELEGRAM_CHAT_ID = str(
            chat_id
        )

        return True


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

async def send_message(
    message,
    context=None,
):

    chat_id = load_chat_id()

    if not chat_id:

        logger.warning(
            "⚠️ No Telegram Chat ID."
        )

        return False

    try:

        if context is not None:

            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
            )

        else:

            logger.warning(
                "Telegram context unavailable."
            )

            return False

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

    chat_id = (
        update.effective_chat.id
    )

    username = "Telegram User"

    if update.effective_user:

        if update.effective_user.username:

            username = (
                "@"
                + update.effective_user.username
            )

        elif update.effective_user.first_name:

            username = (
                update.effective_user.first_name
            )

    # Automatically capture Chat ID
    save_chat_id(chat_id)

    message = (
        "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"

        "🟢 *BOT CONNECTED*\n\n"

        f"👤 User: {username}\n"
        f"🆔 Chat ID: `{chat_id}`\n\n"

        "✅ *Chat ID automatically detected.*\n"
        "✅ *Telegram alerts are now enabled.*\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟡 *MARKET*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "Market: *XAU/USD*\n"
        "Timeframe: *15 Minutes*\n"
        "Automatic Scanner: *ON*\n"
        "Confirmation Engine: *ON*\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "📱 *COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "/scan — Live GOLD scan\n"
        "/status — System status\n"
        "/start — Register Chat ID\n\n"

        "👑 *KING OF XAU_NAS IS READY.*"
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
        "⚙️ *SYSTEM STATUS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"Telegram: {telegram_status}\n"
        f"Twelve Data: {data_status}\n"
        f"Scanner: {scanner_status}\n\n"

        "🟡 Market: XAU/USD\n"
        "⏱ Timeframe: 15min\n\n"

        "🧠 Confirmation Engine: ON\n"
        "🚀 Breakout Detection: ON\n"
        "🔄 Pullback Detection: ON\n"
        "⚡ Reversal Detection: ON\n"
        "🛡️ RSI Protection: ON\n"
        "🛡️ ATR Protection: ON\n"
        "🤖 Automatic Scanner: ON\n"
    )

    if chat_id:

        message += (
            f"\n🆔 Chat ID: `{chat_id}`"
        )

    else:

        message += (
            "\n\n⚠️ Send /start to "
            "register your Chat ID."
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
            "TWELVE_DATA_API_KEY missing."
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
                f"Twelve Data HTTP "
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
            reversed(
                data["values"]
            )
        )

        candles = []

        for item in values:

            try:

                candles.append(
                    {
                        "datetime":
                            item["datetime"],

                        "open":
                            float(item["open"]),

                        "high":
                            float(item["high"]),

                        "low":
                            float(item["low"]),

                        "close":
                            float(item["close"]),
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

def calculate_ema(
    values,
    period,
):

    if len(values) < period:

        return None

    multiplier = (
        2 / (period + 1)
    )

    ema = (
        sum(values[:period])
        / period
    )

    for price in values[period:]:

        ema = (
            (
                price - ema
            )
            * multiplier
        ) + ema

    return ema


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    values,
    period=14,
):

    if len(values) < period + 1:

        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values),
    ):

        change = (
            values[i]
            - values[i - 1]
        )

        if change > 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains),
    ):

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

    rs = (
        avg_gain
        / avg_loss
    )

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

    for i in range(
        1,
        len(candles),
    ):

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

        true_ranges.append(tr)

    atr = (
        sum(
            true_ranges[:period]
        )
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
# MOMENTUM
# ============================================================

def get_momentum(candles):

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
# CONFIRMATION ENGINE
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

    momentum = get_momentum(
        candles
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

    # ========================================================
    # TREND
    # ========================================================

    bullish_trend = (
        price > ema20
        and ema20 > ema50
    )

    bearish_trend = (
        price < ema20
        and ema20 < ema50
    )

    if bullish_trend:

        trend = "BULLISH 📈"

    elif bearish_trend:

        trend = "BEARISH 📉"

    else:

        trend = "RANGING ↔️"

    # ========================================================
    # STRUCTURE
    # ========================================================

    resistance = max(
        highs[-20:-1]
    )

    support = min(
        lows[-20:-1]
    )

    previous_close = closes[-2]

    breakout_up = (
        price > resistance
        and previous_close <= resistance
    )

    breakout_down = (
        price < support
        and previous_close >= support
    )

    # ========================================================
    # ATR DISTANCE
    # ========================================================

    atr_distance = (
        abs(price - ema20) / atr
        if atr > 0
        else 0
    )

    # ========================================================
    # PULLBACK ZONES
    # ========================================================

    bullish_pullback_zone = (
        ema20 - atr * 0.75,
        ema20 + atr * 0.25,
    )

    bearish_pullback_zone = (
        ema20 - atr * 0.25,
        ema20 + atr * 0.75,
    )

    price_in_bullish_pullback = (
        bullish_pullback_zone[0]
        <= price
        <= bullish_pullback_zone[1]
    )

    price_in_bearish_pullback = (
        bearish_pullback_zone[0]
        <= price
        <= bearish_pullback_zone[1]
    )

    # ========================================================
    # RSI
    # ========================================================

    bullish_rsi = (
        50 <= rsi <= 68
    )

    bearish_rsi = (
        32 <= rsi <= 50
    )

    extreme_overbought = (
        rsi >= 75
    )

    extreme_oversold = (
        rsi <= 25
    )

    # ========================================================
    # REVERSAL
    # ========================================================

    recent = candles[-3:]

    bearish_reversal_candle = (
        recent[-1]["close"]
        < recent[-1]["open"]
        and recent[-1]["close"]
        < recent[-2]["close"]
    )

    bullish_reversal_candle = (
        recent[-1]["close"]
        > recent[-1]["open"]
        and recent[-1]["close"]
        > recent[-2]["close"]
    )

    bearish_reversal = (
        extreme_overbought
        and bearish_reversal_candle
        and momentum == "BEARISH"
    )

    bullish_reversal = (
        extreme_oversold
        and bullish_reversal_candle
        and momentum == "BULLISH"
    )

    # ========================================================
    # SETUP TYPE
    # ========================================================

    setup_type = "WAIT"

    if breakout_up:

        setup_type = "BREAKOUT BUY"

    elif breakout_down:

        setup_type = "BREAKOUT SELL"

    elif bearish_reversal:

        setup_type = "REVERSAL SELL"

    elif bullish_reversal:

        setup_type = "REVERSAL BUY"

    elif bullish_trend:

        setup_type = "BULLISH PULLBACK"

    elif bearish_trend:

        setup_type = "BEARISH PULLBACK"

    # ========================================================
    # CONDITIONS
    # ========================================================

    conditions = []
    failed = []

    if bullish_trend:

        conditions.append(
            "Bullish EMA structure"
        )

        if price_in_bullish_pullback:

            conditions.append(
                "Price inside pullback zone"
            )

        else:

            failed.append(
                "Price not yet inside pullback zone"
            )

        if bullish_rsi:

            conditions.append(
                "RSI healthy"
            )

        else:

            failed.append(
                "RSI not yet confirmed"
            )

        if momentum == "BULLISH":

            conditions.append(
                "Bullish momentum"
            )

        else:

            failed.append(
                "Bullish momentum missing"
            )

    if bearish_trend:

        conditions.append(
            "Bearish EMA structure"
        )

        if price_in_bearish_pullback:

            conditions.append(
                "Price inside pullback zone"
            )

        else:

            failed.append(
                "Price not yet inside pullback zone"
            )

        if bearish_rsi:

            conditions.append(
                "RSI healthy"
            )

        else:

            failed.append(
                "RSI not yet confirmed"
            )

        if momentum == "BEARISH":

            conditions.append(
                "Bearish momentum"
            )

        else:

            failed.append(
                "Bearish momentum missing"
            )

    # ========================================================
    # BREAKOUT
    # ========================================================

    if breakout_up:

        if bullish_trend:

            conditions.append(
                "Bullish trend confirmed"
            )

        if momentum == "BULLISH":

            conditions.append(
                "Bullish breakout momentum"
            )

        else:

            failed.append(
                "Breakout momentum missing"
            )

        if rsi < 75:

            conditions.append(
                "RSI not extremely overbought"
            )

        else:

            failed.append(
                "RSI too overbought"
            )

    if breakout_down:

        if bearish_trend:

            conditions.append(
                "Bearish trend confirmed"
            )

        if momentum == "BEARISH":

            conditions.append(
                "Bearish breakout momentum"
            )

        else:

            failed.append(
                "Breakout momentum missing"
            )

        if rsi > 25:

            conditions.append(
                "RSI not extremely oversold"
            )

        else:

            failed.append(
                "RSI too oversold"
            )

    # ========================================================
    # REVERSAL
    # ========================================================

    if setup_type == "REVERSAL SELL":

        conditions = [
            "RSI extremely overbought",
            "Bearish reversal candle",
            "Bearish momentum",
        ]

    elif setup_type == "REVERSAL BUY":

        conditions = [
            "RSI extremely oversold",
            "Bullish reversal candle",
            "Bullish momentum",
        ]

    # ========================================================
    # CONFIRMATION
    # ========================================================

    confirmed = False

    if setup_type == "BREAKOUT BUY":

        confirmed = (
            bullish_trend
            and momentum == "BULLISH"
            and rsi < 75
        )

    elif setup_type == "BREAKOUT SELL":

        confirmed = (
            bearish_trend
            and momentum == "BEARISH"
            and rsi > 25
        )

    elif setup_type == "BULLISH PULLBACK":

        confirmed = (
            bullish_trend
            and price_in_bullish_pullback
            and bullish_rsi
            and momentum == "BULLISH"
        )

    elif setup_type == "BEARISH PULLBACK":

        confirmed = (
            bearish_trend
            and price_in_bearish_pullback
            and bearish_rsi
            and momentum == "BEARISH"
        )

    elif setup_type == "REVERSAL SELL":

        confirmed = bearish_reversal

    elif setup_type == "REVERSAL BUY":

        confirmed = bullish_reversal

    # ========================================================
    # STAGE
    # ========================================================

    if confirmed:

        stage = "CONFIRMED"

    elif len(conditions) >= 2:

        stage = "NEAR CONFIRMATION"

    elif len(conditions) >= 1:

        stage = "SETUP FORMING"

    else:

        stage = "WAIT"

    # ========================================================
    # CONFIDENCE
    # ========================================================

    total_possible = max(
        len(conditions)
        + len(failed),
        1,
    )

    confidence = (
        len(conditions)
        / total_possible
    ) * 100

    if confirmed:

        confidence = max(
            confidence,
            80,
        )

    # ========================================================
    # DIRECTION
    # ========================================================

    if setup_type in (
        "BREAKOUT BUY",
        "BULLISH PULLBACK",
        "REVERSAL BUY",
    ):

        direction = "BUY"

    elif setup_type in (
        "BREAKOUT SELL",
        "BEARISH PULLBACK",
        "REVERSAL SELL",
    ):

        direction = "SELL"

    else:

        direction = "WAIT"

    # ========================================================
    # EXTREME PROTECTION
    # ========================================================

    if (
        bullish_trend
        and rsi >= 75
        and not bearish_reversal
        and not breakout_up
    ):

        stage = "WAIT"
        direction = "WAIT"

        failed.append(
            "Extreme overbought condition"
        )

    if (
        bearish_trend
        and rsi <= 25
        and not bullish_reversal
        and not breakout_down
    ):

        stage = "WAIT"
        direction = "WAIT"

        failed.append(
            "Extreme oversold condition"
        )

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

        pending_type = "WATCH PULLBACK"

        if bullish_trend:

            pending_entry = (
                ema20 - atr * 0.25
            )

        elif bearish_trend:

            pending_entry = (
                ema20 + atr * 0.25
            )

        else:

            pending_entry = None

    return {
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "trend": trend,
        "momentum": momentum,
        "resistance": resistance,
        "support": support,
        "atr_distance": atr_distance,
        "setup_type": setup_type,
        "stage": stage,
        "confirmed": confirmed,
        "direction": direction,
        "confidence": confidence,
        "conditions": conditions,
        "failed": failed,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "pending_type": pending_type,
        "pending_entry": pending_entry,
        "bullish_pullback_zone":
            bullish_pullback_zone,
        "bearish_pullback_zone":
            bearish_pullback_zone,
    }


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(a):

    stage = a["stage"]
    direction = a["direction"]

    if stage == "CONFIRMED":

        if direction == "BUY":

            header = (
                "🚨 *SIGNAL CONFIRMED — BUY* 🚨"
            )

        elif direction == "SELL":

            header = (
                "🚨 *SIGNAL CONFIRMED — SELL* 🚨"
            )

        else:

            header = (
                "🚨 *SIGNAL CONFIRMED* 🚨"
            )

    elif stage == "NEAR CONFIRMATION":

        header = (
            "🟠 *NEAR CONFIRMATION* 🟠"
        )

    elif stage == "SETUP FORMING":

        header = (
            "🟡 *SETUP FORMING* 🟡"
        )

    else:

        header = (
            "🟡 *WAIT / PULLBACK* 🟡"
        )

    message = (
        "👑 *KING OF XAU_NAS — GOLD* 👑\n\n"

        "🟡 *XAU/USD*\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"{header}\n"

        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"📌 Setup: *{a['setup_type']}*\n"
        f"🎯 Stage: *{stage}*\n"
        f"📊 Direction: *{direction}*\n"
        f"💯 Confidence: "
        f"*{a['confidence']:.0f}%*\n\n"

        f"💰 Price: "
        f"`${a['price']:,.2f}`\n"

        f"📈 Trend: *{a['trend']}*\n"

        f"⚡ Momentum: *{a['momentum']}*\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *TECHNICAL ANALYSIS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"EMA 20: `{a['ema20']:,.2f}`\n"
        f"EMA 50: `{a['ema50']:,.2f}`\n"
        f"RSI 14: `{a['rsi']:.1f}`\n"
        f"ATR 14: `{a['atr']:.2f}`\n"

        f"EMA Distance: "
        f"`{a['atr_distance']:.2f} ATR`\n\n"
    )

    # ========================================================
    # CONFIRMED TRADE
    # ========================================================

    if a["confirmed"]:

        message += (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🚨 *ALL CONDITIONS MET*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        for condition in a["conditions"]:

            message += (
                f"✅ {condition}\n"
            )

        message += (
            "\n━━━━━━━━━━━━━━━━━━━━\n"
            "🎯 *TRADE LEVELS*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"

            f"💰 Entry: "
            f"`${a['entry']:,.2f}`\n"

            f"🛑 SL: "
            f"`${a['stop_loss']:,.2f}`\n"

            f"🥇 TP1: "
            f"`${a['tp1']:,.2f}`\n"

            f"🥈 TP2: "
            f"`${a['tp2']:,.2f}`\n"

            f"🏆 TP3: "
            f"`${a['tp3']:,.2f}`\n\n"

            "⏳ *PENDING ORDER IDEA*\n"

            f"{a['pending_type']}: "
            f"`{a['pending_entry']:,.2f}`\n\n"
        )

    # ========================================================
    # FORMING
    # ========================================================

    elif stage in (
        "NEAR CONFIRMATION",
        "SETUP FORMING",
    ):

        message += (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🧠 *CONFIRMATION CHECK*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        for condition in a["conditions"]:

            message += (
                f"✅ {condition}\n"
            )

        for failed in a["failed"]:

            message += (
                f"⏳ {failed}\n"
            )

        message += (
            "\n⚠️ *No confirmed trade yet.*\n"
            "Wait for all required conditions.\n\n"
        )

    # ========================================================
    # WAIT
    # ========================================================

    else:

        message += (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🟡 *ACTION: WAIT*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"

            "🚫 Do not chase the current price.\n"
            "Wait for confirmation.\n\n"
        )

        if a["pending_entry"]:

            message += (
                f"⏳ Watch level: "
                f"`{a['pending_entry']:,.2f}`\n\n"
            )

    # ========================================================
    # PULLBACK ZONE
    # ========================================================

    if a["trend"] == "BULLISH 📈":

        zone = a[
            "bullish_pullback_zone"
        ]

        message += (
            "🔄 *BULLISH PULLBACK ZONE*\n"

            f"`{zone[0]:,.2f}` → "
            f"`{zone[1]:,.2f}`\n\n"
        )

    elif a["trend"] == "BEARISH 📉":

        zone = a[
            "bearish_pullback_zone"
        ]

        message += (
            "🔄 *BEARISH PULLBACK ZONE*\n"

            f"`{zone[0]:,.2f}` → "
            f"`{zone[1]:,.2f}`\n\n"
        )

    # ========================================================
    # SYSTEM
    # ========================================================

    message += (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ *SYSTEM*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "⏱ Timeframe: *15min*\n"
        "📡 Data: *Twelve Data*\n"
        "🧠 Confirmation Engine: *ON*\n"
        "🚀 Breakout Detection: *ON*\n"
        "🔄 Pullback Detection: *ON*\n"
        "⚡ Reversal Detection: *ON*\n"
        "🛡️ RSI Protection: *ON*\n"
        "🛡️ ATR Protection: *ON*\n"
        "🤖 Automatic Scanner: *ON*\n\n"

        "⚠️ Market information is for analysis only.\n"
        "Not financial advice. Manage risk carefully."
    )

    return message


# ============================================================
# SCAN GOLD
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
        f"{analysis['stage']} | "
        f"{analysis['setup_type']} | "
        f"{analysis['direction']} | "
        f"Price={analysis['price']:.2f} | "
        f"RSI={analysis['rsi']:.1f}"
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
            "❌ Unable to retrieve GOLD data."
        )

        return

    # Register Chat ID when user uses /scan too
    if update.effective_chat:

        save_chat_id(
            update.effective_chat.id
        )

    await update.message.reply_text(
        format_signal(analysis),
        parse_mode="Markdown",
    )


# ============================================================
# AUTOMATIC SCANNER
# ============================================================

async def automatic_scanner(
    application: Application,
):

    global scanner_running
    global last_confirmed_key
    global last_confirmed_time
    global last_setup_key
    global last_setup_stage

    scanner_running = True

    logger.info(
        "🟢 Advanced automatic scanner started."
    )

    try:

        while True:

            try:

                analysis = await asyncio.to_thread(
                    scan_gold
                )

                if analysis:

                    stage = analysis[
                        "stage"
                    ]

                    setup = analysis[
                        "setup_type"
                    ]

                    direction = analysis[
                        "direction"
                    ]

                    price = analysis[
                        "price"
                    ]

                    price_zone = round(
                        price,
                        1,
                    )

                    setup_key = (
                        f"{setup}_"
                        f"{direction}_"
                        f"{price_zone}"
                    )

                    # ==================================================
                    # CONFIRMED SIGNAL
                    # ==================================================

                    if (
                        analysis["confirmed"]
                        and stage == "CONFIRMED"
                    ):

                        confirmed_key = (
                            f"{setup}_"
                            f"{direction}_"
                            f"{round(price, 1)}"
                        )

                        now = time.time()

                        should_send = (
                            confirmed_key
                            != last_confirmed_key
                            or
                            now
                            - last_confirmed_time
                            >= 1800
                        )

                        if should_send:

                            message = format_signal(
                                analysis
                            )

                            sent = await send_message(
                                message,
                                application,
                            )

                            if sent:

                                last_confirmed_key = (
                                    confirmed_key
                                )

                                last_confirmed_time = (
                                    now
                                )

                                logger.info(
                                    "🚨 CONFIRMED "
                                    "SIGNAL SENT."
                                )

                    # ==================================================
                    # FORMING SETUP
                    # ==================================================

                    elif stage in (
                        "SETUP FORMING",
                        "NEAR CONFIRMATION",
                    ):

                        if (
                            setup_key
                            != last_setup_key
                            or
                            stage
                            != last_setup_stage
                        ):

                            message = format_signal(
                                analysis
                            )

                            sent = await send_message(
                                message,
                                application,
                            )

                            if sent:

                                last_setup_key = (
                                    setup_key
                                )

                                last_setup_stage = (
                                    stage
                                )

                                logger.info(
                                    f"🟠 {stage} "
                                    "notification sent."
                                )

                    else:

                        last_setup_stage = stage

                # Wait until next scan
                await asyncio.sleep(
                    SCAN_INTERVAL_SECONDS
                )

            except asyncio.CancelledError:

                logger.info(
                    "🛑 Automatic scanner "
                    "cancelled."
                )

                raise

            except Exception as e:

                logger.exception(
                    f"Automatic scanner error: {e}"
                )

                await asyncio.sleep(
                    30
                )

    finally:

        scanner_running = False

        logger.info(
            "🔴 Automatic scanner stopped."
        )


# ============================================================
# POST INIT
# ============================================================

async def post_init(
    application: Application,
):

    chat_id = load_chat_id()

    if chat_id:

        logger.info(
            f"🆔 Saved Chat ID available: "
            f"{chat_id}"
        )

    else:

        logger.warning(
            "⚠️ No Chat ID saved. "
            "Send /start in Telegram."
        )

    # Start automatic scanner INSIDE
    # Telegram's event loop.
    application.create_task(
        automatic_scanner(
            application
        ),
        name="gold_automatic_scanner",
    )

    logger.info(
        "🟢 Automatic scanner task created."
    )


# ============================================================
# POST SHUTDOWN
# ============================================================

async def post_shutdown(
    application: Application,
):

    logger.info(
        "🛑 Telegram application shutting down."
    )

    global scanner_running

    scanner_running = False

    logger.info(
        "🛑 KING OF XAU_NAS shutdown complete."
    )


# ============================================================
# CREATE TELEGRAM APPLICATION
# ============================================================

def create_application():

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN missing."
        )

    application = (
        Application.builder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
        .post_init(
            post_init
        )
        .post_shutdown(
            post_shutdown
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
            "scan",
            scan_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    return application


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info(
        "========================================"
    )

    logger.info(
        "👑 KING OF XAU_NAS — GOLD"
    )

    logger.info(
        "🟢 Starting advanced engine..."
    )

    logger.info(
        f"Market: {XAU_SYMBOL}"
    )

    logger.info(
        f"Timeframe: {INTERVAL}"
    )

    logger.info(
        "🚀 Breakout engine: ON"
    )

    logger.info(
        "🔄 Pullback engine: ON"
    )

    logger.info(
        "⚡ Reversal engine: ON"
    )

    logger.info(
        "🧠 Confirmation engine: ON"
    )

    logger.info(
        "========================================"
    )

    # ========================================================
    # ENVIRONMENT CHECK
    # ========================================================

    if not TELEGRAM_BOT_TOKEN:

        logger.error(
            "❌ TELEGRAM_BOT_TOKEN missing."
        )

        return

    if not TWELVE_DATA_API_KEY:

        logger.error(
            "❌ TWELVE_DATA_API_KEY missing."
        )

        return

    # ========================================================
    # FLASK
    # ========================================================

    try:

        flask_thread = __import__(
            "threading"
        ).Thread(
            target=run_flask,
            daemon=True,
            name="flask_server",
        )

        flask_thread.start()

        logger.info(
            f"🟢 Flask server launched "
            f"on port {PORT}."
        )

    except Exception as e:

        logger.exception(
            f"Flask startup error: {e}"
        )

        return

    # ========================================================
    # TELEGRAM
    # ========================================================

    application = create_application()

    logger.info(
        "🟢 Telegram application created."
    )

    # ========================================================
    # ONLINE
    # ========================================================

    logger.info(
        "========================================"
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
        "🧠 Confirmation engine: ONLINE"
    )

    logger.info(
        "🤖 Automatic scanner: ONLINE"
    )

    logger.info(
        "========================================"
    )

    # ========================================================
    # RUN TELEGRAM
    # ========================================================

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
