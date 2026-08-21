import os
import json
import time
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
# 👑 KING OF XAU_NAS AI — GOLD
# ADVANCED CONFIRMATION + SCALPING ENGINE
# TELEGRAM / RENDER VERSION
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
# MARKET SETTINGS — NORMAL ENGINE
# ============================================================

XAU_SYMBOL = "XAU/USD"

NORMAL_INTERVAL = "15min"
NORMAL_OUTPUT_SIZE = 100

SCAN_INTERVAL_SECONDS = 300


# ============================================================
# MARKET SETTINGS — SCALPING ENGINE
# ============================================================

SCALP_FAST_INTERVAL = "1min"
SCALP_TREND_INTERVAL = "5min"

SCALP_FAST_OUTPUT_SIZE = 150
SCALP_TREND_OUTPUT_SIZE = 100

# Automatic scalp scanner checks every minute.
SCALP_SCAN_INTERVAL_SECONDS = 60

# Minimum confidence required before automatic scalp alert.
SCALP_MIN_CONFIDENCE = 80

# Minimum time between repeated scalp alerts.
SCALP_COOLDOWN_SECONDS = 300

# ATR multipliers.
SCALP_SL_ATR_MULTIPLIER = 1.20
SCALP_TP1_ATR_MULTIPLIER = 0.80
SCALP_TP2_ATR_MULTIPLIER = 1.50
SCALP_TP3_ATR_MULTIPLIER = 2.20

# Maximum distance from EMA21 in ATR units.
# Prevents chasing extremely extended candles.
SCALP_MAX_EXTENSION_ATR = 1.50


# ============================================================
# STORAGE
# ============================================================

CHAT_ID_FILE = "telegram_chat_id.json"

TELEGRAM_CHAT_ID = None


# ============================================================
# NORMAL ALERT STATE
# ============================================================

last_confirmed_key = None
last_confirmed_time = 0

last_setup_key = None
last_setup_stage = None

scanner_running = False


# ============================================================
# SCALPING ALERT STATE
# ============================================================

scalp_enabled = True
scalp_scanner_running = False

last_scalp_key = None
last_scalp_time = 0

last_scalp_stage = None


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
        <title>King of XAU_NAS AI</title>
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

        <h1>👑 KING OF XAU_NAS AI</h1>

        <h2>🟢 BOT ONLINE</h2>

        <p>🟡 XAU/USD</p>
        <p>🧠 15M Confirmation Engine</p>
        <p>⚡ 1M/5M Scalping Engine</p>
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
        "normal_timeframe": NORMAL_INTERVAL,
        "scalp_fast_timeframe": SCALP_FAST_INTERVAL,
        "scalp_trend_timeframe": SCALP_TREND_INTERVAL,
        "normal_scanner": scanner_running,
        "scalp_scanner": scalp_scanner_running,
        "scalp_enabled": scalp_enabled,
    }


def run_flask():

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
                    "chat_id": TELEGRAM_CHAT_ID,
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

    chat_id = update.effective_chat.id

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

    save_chat_id(chat_id)

    message = (
        "👑 *KING OF XAU_NAS AI* 👑\n\n"

        "🟢 *BOT CONNECTED*\n\n"

        f"👤 User: {username}\n"
        f"🆔 Chat ID: `{chat_id}`\n\n"

        "✅ Chat ID automatically detected.\n"
        "✅ Telegram alerts enabled.\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟡 *NORMAL AI ENGINE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "Market: *XAU/USD*\n"
        "Timeframe: *15 Minutes*\n"
        "Confirmation Engine: *ON*\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ *SCALPING ENGINE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "Trend TF: *5 Minutes*\n"
        "Trigger TF: *1 Minute*\n"
        f"Minimum Confidence: *{SCALP_MIN_CONFIDENCE}%*\n"
        f"Automatic Scalping: "
        f"*{'ON' if scalp_enabled else 'OFF'}*\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "📱 *COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "/scan — 15M GOLD scan\n"
        "/scalp — Instant scalp scan\n"
        "/scalpon — Enable scalp alerts\n"
        "/scalpoff — Disable scalp alerts\n"
        "/scalpstatus — Scalp status\n"
        "/status — Full system status\n"
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

    normal_status = (
        "🟢 ON"
        if scanner_running
        else "🔴 OFF"
    )

    scalp_status = (
        "🟢 ON"
        if scalp_enabled
        else "🔴 OFF"
    )

    scalp_scanner_status = (
        "🟢 RUNNING"
        if scalp_scanner_running
        else "🔴 OFF"
    )

    message = (
        "👑 *KING OF XAU_NAS AI* 👑\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ *SYSTEM STATUS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"Telegram: {telegram_status}\n"
        f"Twelve Data: {data_status}\n"
        f"15M Scanner: {normal_status}\n"
        f"Scalping Alerts: {scalp_status}\n"
        f"Scalp Scanner: {scalp_scanner_status}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "🟡 *NORMAL ENGINE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "Market: XAU/USD\n"
        "Timeframe: 15min\n"
        "EMA 20/50: ON\n"
        "RSI 14: ON\n"
        "ATR 14: ON\n"
        "Breakout: ON\n"
        "Pullback: ON\n"
        "Reversal: ON\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ *SCALPING ENGINE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "Trend: 5min\n"
        "Trigger: 1min\n"
        "EMA: 9 / 21 / 50\n"
        "RSI: 7\n"
        "ATR: 14\n"
        "Momentum Filter: ON\n"
        "Extension Protection: ON\n"
        "Confidence Filter: ON\n"
        f"Minimum Confidence: "
        f"{SCALP_MIN_CONFIDENCE}%\n"
        f"Cooldown: "
        f"{SCALP_COOLDOWN_SECONDS // 60} minutes\n"
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
# TWELVE DATA GENERIC
# ============================================================

def get_market_data(
    interval,
    output_size,
):

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
        "interval": interval,
        "outputsize": output_size,
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
                f"{response.status_code} "
                f"for {interval}"
            )

            return None

        data = response.json()

        if "values" not in data:

            logger.error(
                f"Twelve Data {interval} "
                f"error: {data}"
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
                f"Not enough {interval} candles."
            )

            return None

        return candles

    except Exception as e:

        logger.error(
            f"Market data error "
            f"{interval}: {e}"
        )

        return None


def get_gold_data():

    return get_market_data(
        NORMAL_INTERVAL,
        NORMAL_OUTPUT_SIZE,
    )


def get_scalp_fast_data():

    return get_market_data(
        SCALP_FAST_INTERVAL,
        SCALP_FAST_OUTPUT_SIZE,
    )


def get_scalp_trend_data():

    return get_market_data(
        SCALP_TREND_INTERVAL,
        SCALP_TREND_OUTPUT_SIZE,
    )


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
# NORMAL 15M CONFIRMATION ENGINE
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

    atr_distance = (
        abs(price - ema20) / atr
        if atr > 0
        else 0
    )

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

    if confirmed:

        stage = "CONFIRMED"

    elif len(conditions) >= 2:

        stage = "NEAR CONFIRMATION"

    elif len(conditions) >= 1:

        stage = "SETUP FORMING"

    else:

        stage = "WAIT"

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

    if direction == "BUY":

        entry = price
        stop_loss = price - atr * 1.5
        tp1 = price + atr
        tp2 = price + atr * 2
        tp3 = price + atr * 3

        pending_type = "BUY LIMIT"
        pending_entry = price - atr * 0.50

    elif direction == "SELL":

        entry = price
        stop_loss = price + atr * 1.5
        tp1 = price - atr
        tp2 = price - atr * 2
        tp3 = price - atr * 3

        pending_type = "SELL LIMIT"
        pending_entry = price + atr * 0.50

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
# FORMAT NORMAL SIGNAL
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

        "🟡 *XAU/USD — NORMAL AI*\n"

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

    message += (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ *NORMAL SYSTEM*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "⏱ Timeframe: *15min*\n"
        "📡 Data: *Twelve Data*\n"
        "🧠 Confirmation: *ON*\n"
        "🚀 Breakout: *ON*\n"
        "🔄 Pullback: *ON*\n"
        "⚡ Reversal: *ON*\n"
        "🛡️ RSI Protection: *ON*\n"
        "🛡️ ATR Protection: *ON*\n\n"

        "⚠️ Analysis only. "
        "Not financial advice."
    )

    return message


# ============================================================
# SCAN GOLD
# ============================================================

def scan_gold():

    logger.info(
        "🔎 Scanning XAU/USD 15M..."
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
        f"15M | "
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
        "🔎 *Scanning XAU/USD 15M...*\n\n"
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

    if update.effective_chat:

        save_chat_id(
            update.effective_chat.id
        )

    await update.message.reply_text(
        format_signal(analysis),
        parse_mode="Markdown",
    )


# ============================================================
# ============================================================
# ⚡ SCALPING ENGINE
# ============================================================
# ============================================================

def get_scalp_trend(
    candles
):

    closes = [
        candle["close"]
        for candle in candles
    ]

    ema20 = calculate_ema(
        closes,
        20,
    )

    ema50 = calculate_ema(
        closes,
        50,
    )

    if (
        ema20 is None
        or ema50 is None
    ):

        return "NEUTRAL"

    price = closes[-1]

    if (
        price > ema20
        and ema20 > ema50
    ):

        return "BULLISH"

    if (
        price < ema20
        and ema20 < ema50
    ):

        return "BEARISH"

    return "NEUTRAL"


def analyze_scalp(
    fast_candles,
    trend_candles,
):

    if (
        not fast_candles
        or not trend_candles
    ):

        return None

    closes = [
        candle["close"]
        for candle in fast_candles
    ]

    highs = [
        candle["high"]
        for candle in fast_candles
    ]

    lows = [
        candle["low"]
        for candle in fast_candles
    ]

    price = closes[-1]

    ema9 = calculate_ema(
        closes,
        9,
    )

    ema21 = calculate_ema(
        closes,
        21,
    )

    ema50 = calculate_ema(
        closes,
        50,
    )

    rsi = calculate_rsi(
        closes,
        7,
    )

    atr = calculate_atr(
        fast_candles,
        14,
    )

    trend_5m = get_scalp_trend(
        trend_candles
    )

    momentum = get_momentum(
        fast_candles
    )

    if any(
        value is None
        for value in (
            ema9,
            ema21,
            ema50,
            rsi,
            atr,
        )
    ):

        return None

    if atr <= 0:

        return None

    # --------------------------------------------------------
    # FAST TREND
    # --------------------------------------------------------

    fast_bullish = (
        price > ema9
        and ema9 > ema21
        and ema21 > ema50
    )

    fast_bearish = (
        price < ema9
        and ema9 < ema21
        and ema21 < ema50
    )

    # --------------------------------------------------------
    # 5M + 1M ALIGNMENT
    # --------------------------------------------------------

    bullish_alignment = (
        trend_5m == "BULLISH"
        and fast_bullish
    )

    bearish_alignment = (
        trend_5m == "BEARISH"
        and fast_bearish
    )

    # --------------------------------------------------------
    # RECENT STRUCTURE
    # --------------------------------------------------------

    lookback_high = max(
        highs[-10:-1]
    )

    lookback_low = min(
        lows[-10:-1]
    )

    previous_close = closes[-2]

    breakout_buy = (
        price > lookback_high
        and previous_close <= lookback_high
    )

    breakout_sell = (
        price < lookback_low
        and previous_close >= lookback_low
    )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    bullish_rsi = (
        52 <= rsi <= 72
    )

    bearish_rsi = (
        28 <= rsi <= 48
    )

    # Avoid chasing extreme RSI.
    rsi_too_high = rsi >= 78
    rsi_too_low = rsi <= 22

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    bullish_momentum = (
        momentum == "BULLISH"
    )

    bearish_momentum = (
        momentum == "BEARISH"
    )

    # --------------------------------------------------------
    # EMA PULLBACK
    # --------------------------------------------------------

    bullish_pullback = (
        ema21 - atr * 0.30
        <= price
        <= ema9 + atr * 0.25
    )

    bearish_pullback = (
        ema9 - atr * 0.25
        <= price
        <= ema21 + atr * 0.30
    )

    # --------------------------------------------------------
    # EXTENSION
    # --------------------------------------------------------

    extension = (
        abs(price - ema21)
        / atr
    )

    extended = (
        extension
        > SCALP_MAX_EXTENSION_ATR
    )

    # --------------------------------------------------------
    # CANDLE DIRECTION
    # --------------------------------------------------------

    current = fast_candles[-1]
    previous = fast_candles[-2]

    bullish_candle = (
        current["close"]
        > current["open"]
        and current["close"]
        >= previous["close"]
    )

    bearish_candle = (
        current["close"]
        < current["open"]
        and current["close"]
        <= previous["close"]
    )

    # --------------------------------------------------------
    # SCORE BUY
    # --------------------------------------------------------

    buy_score = 0
    sell_score = 0

    buy_conditions = []
    sell_conditions = []

    buy_failed = []
    sell_failed = []

    if trend_5m == "BULLISH":

        buy_score += 20
        buy_conditions.append(
            "5M bullish trend"
        )

    else:

        buy_failed.append(
            "5M bullish trend missing"
        )

    if fast_bullish:

        buy_score += 20
        buy_conditions.append(
            "1M EMA 9/21/50 bullish"
        )

    else:

        buy_failed.append(
            "1M EMA alignment missing"
        )

    if bullish_momentum:

        buy_score += 15
        buy_conditions.append(
            "Bullish candle momentum"
        )

    else:

        buy_failed.append(
            "Bullish momentum missing"
        )

    if bullish_rsi:

        buy_score += 15
        buy_conditions.append(
            "RSI bullish zone"
        )

    else:

        buy_failed.append(
            "RSI not in bullish zone"
        )

    if (
        bullish_pullback
        or breakout_buy
    ):

        buy_score += 15

        if breakout_buy:

            buy_conditions.append(
                "1M structure breakout"
            )

        else:

            buy_conditions.append(
                "EMA pullback zone"
            )

    else:

        buy_failed.append(
            "No pullback/breakout trigger"
        )

    if bullish_candle:

        buy_score += 10
        buy_conditions.append(
            "Bullish trigger candle"
        )

    else:

        buy_failed.append(
            "Bullish trigger candle missing"
        )

    if not rsi_too_high:

        buy_score += 5

    else:

        buy_failed.append(
            "RSI excessively overbought"
        )

    # --------------------------------------------------------
    # SCORE SELL
    # --------------------------------------------------------

    if trend_5m == "BEARISH":

        sell_score += 20
        sell_conditions.append(
            "5M bearish trend"
        )

    else:

        sell_failed.append(
            "5M bearish trend missing"
        )

    if fast_bearish:

        sell_score += 20
        sell_conditions.append(
            "1M EMA 9/21/50 bearish"
        )

    else:

        sell_failed.append(
            "1M EMA alignment missing"
        )

    if bearish_momentum:

        sell_score += 15
        sell_conditions.append(
            "Bearish candle momentum"
        )

    else:

        sell_failed.append(
            "Bearish momentum missing"
        )

    if bearish_rsi:

        sell_score += 15
        sell_conditions.append(
            "RSI bearish zone"
        )

    else:

        sell_failed.append(
            "RSI not in bearish zone"
        )

    if (
        bearish_pullback
        or breakout_sell
    ):

        sell_score += 15

        if breakout_sell:

            sell_conditions.append(
                "1M structure breakdown"
            )

        else:

            sell_conditions.append(
                "EMA pullback zone"
            )

    else:

        sell_failed.append(
            "No pullback/breakdown trigger"
        )

    if bearish_candle:

        sell_score += 10
        sell_conditions.append(
            "Bearish trigger candle"
        )

    else:

        sell_failed.append(
            "Bearish trigger candle missing"
        )

    if not rsi_too_low:

        sell_score += 5

    else:

        sell_failed.append(
            "RSI excessively oversold"
        )

    # --------------------------------------------------------
    # DETERMINE DIRECTION
    # --------------------------------------------------------

    direction = "WAIT"
    score = max(
        buy_score,
        sell_score,
    )

    conditions = []
    failed = []

    if (
        buy_score > sell_score
        and bullish_alignment
        and not rsi_too_high
        and not extended
    ):

        direction = "BUY"
        conditions = buy_conditions
        failed = buy_failed

    elif (
        sell_score > buy_score
        and bearish_alignment
        and not rsi_too_low
        and not extended
    ):

        direction = "SELL"
        conditions = sell_conditions
        failed = sell_failed

    else:

        if buy_score >= sell_score:

            conditions = buy_conditions
            failed = buy_failed

        else:

            conditions = sell_conditions
            failed = sell_failed

    # --------------------------------------------------------
    # SETUP TYPE
    # --------------------------------------------------------

    if direction == "BUY":

        if breakout_buy:

            setup_type = "SCALP BREAKOUT BUY"

        elif bullish_pullback:

            setup_type = "SCALP PULLBACK BUY"

        else:

            setup_type = "SCALP MOMENTUM BUY"

    elif direction == "SELL":

        if breakout_sell:

            setup_type = "SCALP BREAKDOWN SELL"

        elif bearish_pullback:

            setup_type = "SCALP PULLBACK SELL"

        else:

            setup_type = "SCALP MOMENTUM SELL"

    else:

        if (
            buy_score
            >= sell_score
        ):

            setup_type = (
                "SCALP BUY WATCH"
            )

        else:

            setup_type = (
                "SCALP SELL WATCH"
            )

    # --------------------------------------------------------
    # EXTENSION PROTECTION
    # --------------------------------------------------------

    if extended:

        direction = "WAIT"

        failed.append(
            "Price too extended from EMA21"
        )

    # --------------------------------------------------------
    # CONFIRMATION
    # --------------------------------------------------------

    confirmed = (
        direction in (
            "BUY",
            "SELL",
        )
        and score
        >= SCALP_MIN_CONFIDENCE
        and not extended
    )

    # Need actual trigger confirmation.
    if confirmed:

        if direction == "BUY":

            confirmed = (
                bullish_alignment
                and bullish_momentum
                and bullish_rsi
                and (
                    bullish_pullback
                    or breakout_buy
                )
                and bullish_candle
                and not rsi_too_high
            )

        elif direction == "SELL":

            confirmed = (
                bearish_alignment
                and bearish_momentum
                and bearish_rsi
                and (
                    bearish_pullback
                    or breakout_sell
                )
                and bearish_candle
                and not rsi_too_low
            )

    # --------------------------------------------------------
    # STAGE
    # --------------------------------------------------------

    if confirmed:

        stage = "SCALP CONFIRMED"

    elif score >= 70:

        stage = "SCALP NEAR CONFIRMATION"

    elif score >= 50:

        stage = "SCALP SETUP FORMING"

    else:

        stage = "SCALP WAIT"

    # --------------------------------------------------------
    # TRADE LEVELS
    # --------------------------------------------------------

    if confirmed:

        entry = price

        if direction == "BUY":

            stop_loss = (
                price
                - atr
                * SCALP_SL_ATR_MULTIPLIER
            )

            tp1 = (
                price
                + atr
                * SCALP_TP1_ATR_MULTIPLIER
            )

            tp2 = (
                price
                + atr
                * SCALP_TP2_ATR_MULTIPLIER
            )

            tp3 = (
                price
                + atr
                * SCALP_TP3_ATR_MULTIPLIER
            )

        else:

            stop_loss = (
                price
                + atr
                * SCALP_SL_ATR_MULTIPLIER
            )

            tp1 = (
                price
                - atr
                * SCALP_TP1_ATR_MULTIPLIER
            )

            tp2 = (
                price
                - atr
                * SCALP_TP2_ATR_MULTIPLIER
            )

            tp3 = (
                price
                - atr
                * SCALP_TP3_ATR_MULTIPLIER
            )

    else:

        entry = price
        stop_loss = None
        tp1 = None
        tp2 = None
        tp3 = None

    return {
        "price": price,
        "ema9": ema9,
        "ema21": ema21,
        "ema50": ema50,
        "rsi": rsi,
        "atr": atr,
        "trend_5m": trend_5m,
        "momentum": momentum,
        "extension": extension,
        "setup_type": setup_type,
        "direction": direction,
        "score": score,
        "confidence": score,
        "stage": stage,
        "confirmed": confirmed,
        "conditions": conditions,
        "failed": failed,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "breakout_buy": breakout_buy,
        "breakout_sell": breakout_sell,
        "bullish_pullback": bullish_pullback,
        "bearish_pullback": bearish_pullback,
        "extended": extended,
    }


# ============================================================
# FORMAT SCALP SIGNAL
# ============================================================

def format_scalp_signal(a):

    if a["confirmed"]:

        if a["direction"] == "BUY":

            header = (
                "🚨 *SCALP BUY CONFIRMED* 🚨"
            )

        else:

            header = (
                "🚨 *SCALP SELL CONFIRMED* 🚨"
            )

    elif a["stage"] == "SCALP NEAR CONFIRMATION":

        header = (
            "🟠 *SCALP NEAR CONFIRMATION* 🟠"
        )

    elif a["stage"] == "SCALP SETUP FORMING":

        header = (
            "🟡 *SCALP SETUP FORMING* 🟡"
        )

    else:

        header = (
            "⚪ *SCALP WAIT* ⚪"
        )

    message = (
        "👑 *KING OF XAU_NAS AI* 👑\n\n"

        "⚡ *SCALPING ENGINE*\n"
        "🟡 *XAU/USD*\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"

        f"{header}\n"

        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"📌 Setup: *{a['setup_type']}*\n"
        f"📊 Direction: *{a['direction']}*\n"
        f"🎯 Stage: *{a['stage']}*\n"
        f"💯 Confidence: "
        f"*{a['confidence']:.0f}%*\n\n"

        f"💰 Price: "
        f"`${a['price']:,.2f}`\n"

        f"📈 5M Trend: "
        f"*{a['trend_5m']}*\n"

        f"⚡ 1M Momentum: "
        f"*{a['momentum']}*\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *SCALP INDICATORS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"EMA 9: `{a['ema9']:,.2f}`\n"
        f"EMA 21: `{a['ema21']:,.2f}`\n"
        f"EMA 50: `{a['ema50']:,.2f}`\n"
        f"RSI 7: `{a['rsi']:.1f}`\n"
        f"ATR 14: `{a['atr']:.2f}`\n"
        f"Extension: "
        f"`{a['extension']:.2f} ATR`\n\n"
    )

    if a["confirmed"]:

        message += (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🚨 *SCALP TRADE LEVELS*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"

            f"🎯 Entry: "
            f"`${a['entry']:,.2f}`\n"

            f"🛑 SL: "
            f"`${a['stop_loss']:,.2f}`\n"

            f"🥇 TP1: "
            f"`${a['tp1']:,.2f}`\n"

            f"🥈 TP2: "
            f"`${a['tp2']:,.2f}`\n"

            f"🏆 TP3: "
            f"`${a['tp3']:,.2f}`\n\n"

            "💡 *Scalp management idea:*\n"
            "Consider protecting the position "
            "after TP1 rather than holding "
            "blindly for TP3.\n\n"
        )

    else:

        message += (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🧠 *SCALP CONFIRMATION*\n"
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
            "\n⚠️ *No confirmed scalp yet.*\n"
            "Wait for the trigger.\n\n"
        )

    message += (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ *SCALPING SETTINGS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "Trend TF: *5min*\n"
        "Trigger TF: *1min*\n"
        "EMA: *9 / 21 / 50*\n"
        "RSI: *7*\n"
        "ATR: *14*\n"

        f"Min Confidence: "
        f"*{SCALP_MIN_CONFIDENCE}%*\n"

        f"Cooldown: "
        f"*{SCALP_COOLDOWN_SECONDS // 60} min*\n\n"

        "⚠️ Scalping is high risk.\n"
        "Analysis only — not financial advice."
    )

    return message


# ============================================================
# SCAN SCALP
# ============================================================

def scan_scalp():

    logger.info(
        "⚡ Scanning XAU/USD 1M + 5M..."
    )

    fast_candles = get_scalp_fast_data()

    if not fast_candles:

        return None

    trend_candles = get_scalp_trend_data()

    if not trend_candles:

        return None

    analysis = analyze_scalp(
        fast_candles,
        trend_candles,
    )

    if not analysis:

        return None

    logger.info(
        f"SCALP | "
        f"{analysis['stage']} | "
        f"{analysis['setup_type']} | "
        f"{analysis['direction']} | "
        f"Score={analysis['confidence']:.0f}% | "
        f"Price={analysis['price']:.2f}"
    )

    return analysis


# ============================================================
# /SCALP
# ============================================================

async def scalp_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if update.effective_chat:

        save_chat_id(
            update.effective_chat.id
        )

    await update.message.reply_text(
        "⚡ *SCALP ENGINE ACTIVATED*\n\n"
        "Analysing XAU/USD...\n"
        "5M trend + 1M trigger\n\n"
        "Please wait...",
        parse_mode="Markdown",
    )

    analysis = await asyncio.to_thread(
        scan_scalp
    )

    if not analysis:

        await update.message.reply_text(
            "❌ Unable to retrieve "
            "scalping market data."
        )

        return

    await update.message.reply_text(
        format_scalp_signal(
            analysis
        ),
        parse_mode="Markdown",
    )


# ============================================================
# /SCALPON
# ============================================================

async def scalpon_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    global scalp_enabled

    if update.effective_chat:

        save_chat_id(
            update.effective_chat.id
        )

    scalp_enabled = True

    await update.message.reply_text(
        "⚡ *SCALPING MODE: ON* ⚡\n\n"

        "🟢 Automatic scalp scanning enabled.\n\n"

        "5M = trend confirmation\n"
        "1M = scalp trigger\n\n"

        f"Minimum confidence: "
        f"*{SCALP_MIN_CONFIDENCE}%*\n"

        f"Cooldown: "
        f"*{SCALP_COOLDOWN_SECONDS // 60} minutes*\n\n"

        "👑 KING OF XAU_NAS is watching.",
        parse_mode="Markdown",
    )


# ============================================================
# /SCALPOFF
# ============================================================

async def scalpoff_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    global scalp_enabled

    if update.effective_chat:

        save_chat_id(
            update.effective_chat.id
        )

    scalp_enabled = False

    await update.message.reply_text(
        "🛑 *SCALPING MODE: OFF*\n\n"
        "Automatic scalp alerts are disabled.\n\n"
        "Your normal 15M AI scanner remains active.",
        parse_mode="Markdown",
    )


# ============================================================
# /SCALPSTATUS
# ============================================================

async def scalpstatus_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    enabled = (
        "🟢 ON"
        if scalp_enabled
        else "🔴 OFF"
    )

    running = (
        "🟢 RUNNING"
        if scalp_scanner_running
        else "🔴 OFF"
    )

    message = (
        "👑 *KING OF XAU_NAS AI*\n\n"

        "⚡ *SCALPING ENGINE STATUS*\n\n"

        f"Automatic Scalp Alerts: {enabled}\n"
        f"Scanner: {running}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 *ENGINE*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "Market: XAU/USD\n"
        "Trend TF: 5min\n"
        "Trigger TF: 1min\n"
        "EMA: 9 / 21 / 50\n"
        "RSI: 7\n"
        "ATR: 14\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "🛡️ *PROTECTION*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"Minimum Confidence: "
        f"{SCALP_MIN_CONFIDENCE}%\n"

        f"SL ATR: "
        f"{SCALP_SL_ATR_MULTIPLIER}\n"

        f"TP1 ATR: "
        f"{SCALP_TP1_ATR_MULTIPLIER}\n"

        f"TP2 ATR: "
        f"{SCALP_TP2_ATR_MULTIPLIER}\n"

        f"TP3 ATR: "
        f"{SCALP_TP3_ATR_MULTIPLIER}\n"

        f"Cooldown: "
        f"{SCALP_COOLDOWN_SECONDS // 60} min\n\n"

        "Use /scalpon or /scalpoff "
        "to control automatic alerts."
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
    )


# ============================================================
# NORMAL AUTOMATIC SCANNER
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
        "🟢 15M automatic scanner started."
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
                                    "🚨 15M CONFIRMED "
                                    "SIGNAL SENT."
                                )

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
                                    f"🟠 15M {stage} "
                                    "notification sent."
                                )

                    else:

                        last_setup_stage = stage

                await asyncio.sleep(
                    SCAN_INTERVAL_SECONDS
                )

            except asyncio.CancelledError:

                logger.info(
                    "🛑 15M scanner cancelled."
                )

                raise

            except Exception as e:

                logger.exception(
                    f"15M scanner error: {e}"
                )

                await asyncio.sleep(
                    30
                )

    finally:

        scanner_running = False

        logger.info(
            "🔴 15M scanner stopped."
        )


# ============================================================
# ⚡ AUTOMATIC SCALPING SCANNER
# ============================================================

async def automatic_scalp_scanner(
    application: Application,
):

    global scalp_scanner_running
    global last_scalp_key
    global last_scalp_time
    global last_scalp_stage

    scalp_scanner_running = True

    logger.info(
        "⚡ Scalping automatic scanner started."
    )

    try:

        while True:

            try:

                # --------------------------------------------
                # If user disabled scalping, stay alive but
                # do not consume market API unnecessarily.
                # --------------------------------------------

                if not scalp_enabled:

                    await asyncio.sleep(
                        10
                    )

                    continue

                analysis = await asyncio.to_thread(
                    scan_scalp
                )

                if analysis:

                    stage = analysis[
                        "stage"
                    ]

                    direction = analysis[
                        "direction"
                    ]

                    setup = analysis[
                        "setup_type"
                    ]

                    price = analysis[
                        "price"
                    ]

                    confidence = analysis[
                        "confidence"
                    ]

                    # ----------------------------------------
                    # CONFIRMED SCALP
                    # ----------------------------------------

                    if (
                        analysis["confirmed"]
                        and direction in (
                            "BUY",
                            "SELL",
                        )
                        and confidence
                        >= SCALP_MIN_CONFIDENCE
                    ):

                        scalp_key = (
                            f"{setup}_"
                            f"{direction}_"
                            f"{round(price, 1)}"
                        )

                        now = time.time()

                        cooldown_passed = (
                            now
                            - last_scalp_time
                            >= SCALP_COOLDOWN_SECONDS
                        )

                        new_signal = (
                            scalp_key
                            != last_scalp_key
                        )

                        if (
                            cooldown_passed
                            and new_signal
                        ):

                            message = (
                                format_scalp_signal(
                                    analysis
                                )
                            )

                            sent = await send_message(
                                message,
                                application,
                            )

                            if sent:

                                last_scalp_key = (
                                    scalp_key
                                )

                                last_scalp_time = (
                                    now
                                )

                                last_scalp_stage = (
                                    stage
                                )

                                logger.info(
                                    "🚨 SCALP "
                                    "SIGNAL SENT."
                                )

                    # ----------------------------------------
                    # NEAR CONFIRMATION
                    # ----------------------------------------

                    elif stage == (
                        "SCALP NEAR CONFIRMATION"
                    ):

                        scalp_key = (
                            f"{setup}_"
                            f"{direction}_"
                            f"{round(price, 1)}"
                        )

                        # Do not spam near-confirmation
                        # messages. Only notify on a new
                        # setup/stage combination.

                        if (
                            scalp_key
                            != last_scalp_key
                            or
                            stage
                            != last_scalp_stage
                        ):

                            # Only notify if reasonably strong.
                            if confidence >= 70:

                                message = (
                                    format_scalp_signal(
                                        analysis
                                    )
                                )

                                sent = (
                                    await send_message(
                                        message,
                                        application,
                                    )
                                )

                                if sent:

                                    last_scalp_key = (
                                        scalp_key
                                    )

                                    last_scalp_stage = (
                                        stage
                                    )

                                    logger.info(
                                        "🟠 SCALP NEAR "
                                        "CONFIRMATION SENT."
                                    )

                await asyncio.sleep(
                    SCALP_SCAN_INTERVAL_SECONDS
                )

            except asyncio.CancelledError:

                logger.info(
                    "🛑 Scalping scanner cancelled."
                )

                raise

            except Exception as e:

                logger.exception(
                    f"Scalping scanner error: {e}"
                )

                await asyncio.sleep(
                    15
                )

    finally:

        scalp_scanner_running = False

        logger.info(
            "🔴 Scalping scanner stopped."
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

    # --------------------------------------------------------
    # NORMAL 15M ENGINE
    # --------------------------------------------------------

    application.create_task(
        automatic_scanner(
            application
        ),
        name="gold_15m_scanner",
    )

    # --------------------------------------------------------
    # SCALPING ENGINE
    # --------------------------------------------------------

    application.create_task(
        automatic_scalp_scanner(
            application
        ),
        name="gold_scalping_scanner",
    )

    logger.info(
        "🟢 Both scanner tasks created."
    )


# ============================================================
# POST SHUTDOWN
# ============================================================

async def post_shutdown(
    application: Application,
):

    global scanner_running
    global scalp_scanner_running

    logger.info(
        "🛑 Telegram application shutting down."
    )

    scanner_running = False
    scalp_scanner_running = False

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

    # Normal commands
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

    # Scalping commands
    application.add_handler(
        CommandHandler(
            "scalp",
            scalp_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "scalpon",
            scalpon_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "scalpoff",
            scalpoff_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "scalpstatus",
            scalpstatus_command,
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
        "👑 KING OF XAU_NAS AI"
    )

    logger.info(
        "🟢 Starting advanced engine..."
    )

    logger.info(
        f"Market: {XAU_SYMBOL}"
    )

    logger.info(
        f"Normal timeframe: "
        f"{NORMAL_INTERVAL}"
    )

    logger.info(
        f"Scalp trend timeframe: "
        f"{SCALP_TREND_INTERVAL}"
    )

    logger.info(
        f"Scalp trigger timeframe: "
        f"{SCALP_FAST_INTERVAL}"
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
        "⚡ Scalping engine: ON"
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

        flask_thread = threading.Thread(
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

    try:

        application = create_application()

    except Exception as e:

        logger.exception(
            f"Telegram application error: {e}"
        )

        return

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
        "👑 KING OF XAU_NAS AI ONLINE"
    )

    logger.info(
        "🟢 Telegram: ONLINE"
    )

    logger.info(
        "🟡 XAU/USD: ONLINE"
    )

    logger.info(
        "🧠 15M Confirmation: ONLINE"
    )

    logger.info(
        "⚡ 1M/5M Scalping: ONLINE"
    )

    logger.info(
        "🤖 Automatic scanners: ONLINE"
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
