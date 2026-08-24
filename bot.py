import os
import time
import math
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
    ContextTypes,
    CallbackQueryHandler,
)

# ============================================================
# KING OF XAU/NAS — SIGNAL TERMINAL
# Straight Entry + Slingshot + Scalp + Health Watchdog
# Designed for Render + Telegram + Twelve Data
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("KING")

# ---------------- ENVIRONMENT ----------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

PORT = int(os.getenv("PORT", "10000"))

# Twelve Data symbols can differ by plan/data package.
# Override these in Render Environment Variables if necessary.
XAU_SYMBOL = os.getenv("XAU_SYMBOL", "XAU/USD").strip()
NAS_SYMBOL = os.getenv("NAS_SYMBOL", "NDX").strip()

# Timeframes
ENTRY_INTERVAL = os.getenv("ENTRY_INTERVAL", "5min")
MAIN_INTERVAL = os.getenv("MAIN_INTERVAL", "15min")
HTF_INTERVAL = os.getenv("HTF_INTERVAL", "1h")

# Scanner timing
SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))
HEARTBEAT_SECONDS = int(os.getenv("HEARTBEAT_SECONDS", "300"))

# Signal thresholds
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "82"))
STRAIGHT_MIN_SCORE = float(os.getenv("STRAIGHT_MIN_SCORE", "8"))
SLINGSHOT_MIN_SCORE = float(os.getenv("SLINGSHOT_MIN_SCORE", "8"))
SCALP_MIN_SCORE = float(os.getenv("SCALP_MIN_SCORE", "8"))

# Don't repeatedly send the same setup
SIGNAL_COOLDOWN_SECONDS = int(os.getenv("SIGNAL_COOLDOWN_SECONDS", "1800"))

# ---------------- STATE ----------------

app = Flask(__name__)

state = {
    "started_at": time.time(),
    "last_scan": None,
    "last_success": None,
    "last_signal": None,
    "last_signal_time": None,
    "scanner_running": False,
    "scanner_errors": 0,
    "api_ok": False,
    "telegram_ok": False,
    "xau_ok": False,
    "nas_ok": False,
    "last_error": "",
}

cache = {}
signal_memory = {}

# ---------------- WEB HEALTH ----------------

@app.get("/")
def home():
    return jsonify({
        "service": "KING OF XAU/NAS SIGNAL TERMINAL",
        "status": "online",
        "scanner_running": state["scanner_running"],
        "last_scan": state["last_scan"],
    })

@app.get("/health")
def health():
    return jsonify({
        "status": "healthy" if state["scanner_running"] else "degraded",
        "scanner_running": state["scanner_running"],
        "api_ok": state["api_ok"],
        "telegram_ok": state["telegram_ok"],
        "xau_ok": state["xau_ok"],
        "nas_ok": state["nas_ok"],
        "last_scan": state["last_scan"],
        "last_success": state["last_success"],
        "last_error": state["last_error"],
        "uptime_seconds": int(time.time() - state["started_at"]),
    })

def run_web():
    # 0.0.0.0 is required by Render.
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

# ---------------- UTILITIES ----------------

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def safe_float(value):
    try:
        return float(value)
    except Exception:
        return None

def clamp(value, low, high):
    return max(low, min(high, value))

def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0.0

def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    result = values[0]
    for v in values[1:]:
        result = alpha * v + (1 - alpha) * result
    return result

def ema_series(values, period):
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result

def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))

    return mean(trs[-period:])

def candle_stats(c):
    rng = max(c["high"] - c["low"], 1e-9)
    body = abs(c["close"] - c["open"])
    upper = c["high"] - max(c["open"], c["close"])
    lower = min(c["open"], c["close"]) - c["low"]
    body_ratio = body / rng
    close_position = (c["close"] - c["low"]) / rng
    return rng, body, upper, lower, body_ratio, close_position

# ---------------- TWELVE DATA ----------------

def fetch_candles(symbol, interval, outputsize=120):
    if not TWELVE_DATA_API_KEY:
        raise RuntimeError("TWELVE_DATA_API_KEY is missing")

    key = f"{symbol}|{interval}|{outputsize}"
    now = time.time()

    # Short cache protects against 429 errors.
    if key in cache and now - cache[key]["time"] < 45:
        return cache[key]["data"], True

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON",
        "order": "ASC",
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    if data.get("status") == "error":
        raise RuntimeError(data.get("message", "Twelve Data returned an error"))

    values = data.get("values")
    if not values:
        raise RuntimeError(f"No candle data returned for {symbol} {interval}")

    candles = []
    for row in values:
        o = safe_float(row.get("open"))
        h = safe_float(row.get("high"))
        l = safe_float(row.get("low"))
        c = safe_float(row.get("close"))
        if None in (o, h, l, c):
            continue
        candles.append({
            "datetime": row.get("datetime", ""),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
        })

    if len(candles) < 60:
        raise RuntimeError(f"Insufficient candles for {symbol} {interval}: {len(candles)}")

    cache[key] = {"time": now, "data": candles}
    state["api_ok"] = True
    return candles, False

# ---------------- MARKET ANALYSIS ----------------

def structure(candles, lookback=12):
    if len(candles) < lookback + 3:
        return None

    recent = candles[-lookback:]
    prior = candles[-(lookback * 2):-lookback]

    recent_high = max(c["high"] for c in recent)
    recent_low = min(c["low"] for c in recent)
    prior_high = max(c["high"] for c in prior) if prior else recent_high
    prior_low = min(c["low"] for c in prior) if prior else recent_low

    return {
        "recent_high": recent_high,
        "recent_low": recent_low,
        "prior_high": prior_high,
        "prior_low": prior_low,
        "break_high": recent_high > prior_high,
        "break_low": recent_low < prior_low,
    }

def trend_data(candles):
    closes = [c["close"] for c in candles]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    r = rsi(closes, 14)
    a = atr(candles, 14)

    if e20 is None or e50 is None or r is None or a is None:
        raise RuntimeError("Unable to calculate indicators")

    return {
        "price": closes[-1],
        "ema20": e20,
        "ema50": e50,
        "rsi": r,
        "atr": a,
    }

def build_signal(symbol, candles5, candles15, candles1h):
    """
    Returns the strongest qualifying signal only.
    No WAIT signals are returned.
    """

    if len(candles5) < 60 or len(candles15) < 60 or len(candles1h) < 60:
        return None

    c5 = candles5[-1]
    prev5 = candles5[-2]

    d5 = trend_data(candles5)
    d15 = trend_data(candles15)
    d1h = trend_data(candles1h)

    s5 = structure(candles5, 12)
    s15 = structure(candles15, 12)

    rng, body, upper, lower, body_ratio, close_pos = candle_stats(c5)
    avg_range = mean([candle_stats(c)[0] for c in candles5[-21:-1]])

    if avg_range <= 0:
        return None

    displacement = rng >= avg_range * 1.35 and body_ratio >= 0.60
    bullish_candle = c5["close"] > c5["open"]
    bearish_candle = c5["close"] < c5["open"]

    bullish_trend = d15["ema20"] > d15["ema50"] and d1h["ema20"] >= d1h["ema50"]
    bearish_trend = d15["ema20"] < d15["ema50"] and d1h["ema20"] <= d1h["ema50"]

    bullish_momentum = 54 <= d5["rsi"] <= 76
    bearish_momentum = 24 <= d5["rsi"] <= 46

    breakout_up = c5["close"] > s5["prior_high"]
    breakout_down = c5["close"] < s5["prior_low"]

    # Previous candle direction helps identify a clean impulse.
    prev_bull = prev5["close"] > prev5["open"]
    prev_bear = prev5["close"] < prev5["open"]

    # ---------- STRAIGHT BUY ----------
    straight_buy_score = 0
    if bullish_trend: straight_buy_score += 3
    if displacement and bullish_candle and close_pos >= 0.72: straight_buy_score += 2
    if breakout_up: straight_buy_score += 2
    if bullish_momentum: straight_buy_score += 1
    if c5["close"] > d5["ema20"]: straight_buy_score += 1
    if prev_bull: straight_buy_score += 1

    # ---------- STRAIGHT SELL ----------
    straight_sell_score = 0
    if bearish_trend: straight_sell_score += 3
    if displacement and bearish_candle and close_pos <= 0.28: straight_sell_score += 2
    if breakout_down: straight_sell_score += 2
    if bearish_momentum: straight_sell_score += 1
    if c5["close"] < d5["ema20"]: straight_sell_score += 1
    if prev_bear: straight_sell_score += 1

    # ---------- SLINGSHOT ----------
    # Impulse happened recently, followed by a controlled pullback,
    # then the latest candle starts continuation.
    recent = candles5[-6:-1]
    recent_high = max(x["high"] for x in recent)
    recent_low = min(x["low"] for x in recent)

    pullback_buy = (
        d15["ema20"] > d15["ema50"]
        and c5["low"] <= d5["ema20"] * 1.0015
        and bullish_candle
        and c5["close"] > prev5["high"]
    )

    pullback_sell = (
        d15["ema20"] < d15["ema50"]
        and c5["high"] >= d5["ema20"] * 0.9985
        and bearish_candle
        and c5["close"] < prev5["low"]
    )

    slingshot_buy_score = 0
    if d15["ema20"] > d15["ema50"]: slingshot_buy_score += 3
    if pullback_buy: slingshot_buy_score += 3
    if d5["rsi"] > 52: slingshot_buy_score += 1
    if c5["close"] > d5["ema20"]: slingshot_buy_score += 1
    if c5["close"] > recent_high: slingshot_buy_score += 1

    slingshot_sell_score = 0
    if d15["ema20"] < d15["ema50"]: slingshot_sell_score += 3
    if pullback_sell: slingshot_sell_score += 3
    if d5["rsi"] < 48: slingshot_sell_score += 1
    if c5["close"] < d5["ema20"]: slingshot_sell_score += 1
    if c5["close"] < recent_low: slingshot_sell_score += 1

    candidates = []

    if straight_buy_score >= STRAIGHT_MIN_SCORE and straight_buy_score > straight_sell_score:
        candidates.append(("STRAIGHT BUY", straight_buy_score))

    if straight_sell_score >= STRAIGHT_MIN_SCORE and straight_sell_score > straight_buy_score:
        candidates.append(("STRAIGHT SELL", straight_sell_score))

    if slingshot_buy_score >= SLINGSHOT_MIN_SCORE and slingshot_buy_score > slingshot_sell_score:
        candidates.append(("SLINGSHOT BUY", slingshot_buy_score))

    if slingshot_sell_score >= SLINGSHOT_MIN_SCORE and slingshot_sell_score > slingshot_buy_score:
        candidates.append(("SLINGSHOT SELL", slingshot_sell_score))

    if not candidates:
        return None

    setup, score = max(candidates, key=lambda x: x[1])
    confidence = clamp(72 + score * 3, 0, 98)

    if confidence < MIN_CONFIDENCE:
        return None

    direction_buy = "BUY" in setup
    entry = c5["close"]

    # Conservative ATR-based levels.
    risk = max(d5["atr"] * 1.15, rng * 0.85)

    if direction_buy:
        structural_sl = min(
            c5["low"],
            prev5["low"],
            s5["recent_low"],
        )
        sl = min(structural_sl, entry - risk)
        risk_distance = max(entry - sl, d5["atr"] * 0.75)
        sl = entry - risk_distance
    else:
        structural_sl = max(
            c5["high"],
            prev5["high"],
            s5["recent_high"],
        )
        sl = max(structural_sl, entry + risk)
        risk_distance = max(sl - entry, d5["atr"] * 0.75)
        sl = entry + risk_distance

    if direction_buy:
        tp1 = entry + risk_distance * 1.0
        tp2 = entry + risk_distance * 2.0
        tp3 = entry + risk_distance * 3.0
    else:
        tp1 = entry - risk_distance * 1.0
        tp2 = entry - risk_distance * 2.0
        tp3 = entry - risk_distance * 3.0

    return {
        "symbol": symbol,
        "setup": setup,
        "confidence": round(confidence),
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rsi": d5["rsi"],
        "ema20": d15["ema20"],
        "ema50": d15["ema50"],
        "atr": d5["atr"],
        "time": utc_now(),
        "candle_time": c5["datetime"],
    }

# ---------------- SIGNAL FORMATTING ----------------

def fmt_price(value):
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 100:
        return f"{value:,.2f}"
    return f"{value:.4f}"

def signal_key(signal):
    return (
        signal["symbol"],
        signal["setup"],
        signal["candle_time"],
        round(signal["entry"], 4),
    )

def format_signal(s):
    buy = "BUY" in s["setup"]
    icon = "🟢" if buy else "🔴"
    setup_icon = "⚡" if "STRAIGHT" in s["setup"] else "🏹"

    return (
        f"{icon} <b>{s['setup']}</b>\n"
        f"<b>{s['symbol']}</b>\n\n"
        f"{setup_icon} <b>CONFIDENCE: {s['confidence']}%</b>\n\n"
        f"💰 <b>ENTRY:</b> {fmt_price(s['entry'])}\n"
        f"🛑 <b>STOP LOSS:</b> {fmt_price(s['sl'])}\n\n"
        f"🎯 <b>TP1:</b> {fmt_price(s['tp1'])}\n"
        f"🎯 <b>TP2:</b> {fmt_price(s['tp2'])}\n"
        f"🎯 <b>TP3:</b> {fmt_price(s['tp3'])}\n\n"
        f"📊 RSI: {s['rsi']:.1f}\n"
        f"📈 EMA20/50: {fmt_price(s['ema20'])} / {fmt_price(s['ema50'])}\n"
        f"📐 ATR: {fmt_price(s['atr'])}\n"
        f"⏱️ Entry: {ENTRY_INTERVAL} | HTF: {MAIN_INTERVAL}\n\n"
        f"🕐 {s['time']}\n"
        f"👑 <b>KING OF XAU/NAS</b>\n"
        f"<i>Signal only — no WAIT messages.</i>"
    )

# ---------------- TELEGRAM ----------------

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📡 SIGNALS", callback_data="signals"),
            InlineKeyboardButton("❤️ HEALTH", callback_data="health"),
        ],
        [
            InlineKeyboardButton("🥇 XAUUSD", callback_data="xau"),
            InlineKeyboardButton("📈 NAS100", callback_data="nas"),
        ],
    ])

async def send_text(application, text):
    if not TELEGRAM_CHAT_ID:
        return False
    try:
        await application.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        state["telegram_ok"] = True
        return True
    except Exception as exc:
        state["telegram_ok"] = False
        state["last_error"] = f"Telegram send: {exc}"
        log.exception("Telegram send failed")
        return False

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state["telegram_ok"] = True
    text = (
        "👑 <b>KING OF XAU/NAS</b>\n"
        "<b>PRO SIGNAL TERMINAL</b>\n\n"
        "🟢 Straight Buy/Sell\n"
        "🏹 Slingshot Buy/Sell\n"
        "⚡ Signal-only engine\n"
        "🛡️ Duplicate protection\n"
        "🔄 Auto-recovery watchdog\n\n"
        "The bot stays silent when there is no valid setup.\n\n"
        "Use /health to check the scanner."
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )

async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state["telegram_ok"] = True
    uptime = int(time.time() - state["started_at"])
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60

    text = (
        "❤️ <b>KING OF XAU/NAS — HEALTH</b>\n\n"
        f"{'🟢' if state['scanner_running'] else '🔴'} Scanner: "
        f"<b>{'RUNNING' if state['scanner_running'] else 'STOPPED'}</b>\n"
        f"{'🟢' if state['api_ok'] else '🔴'} Market Data: "
        f"<b>{'CONNECTED' if state['api_ok'] else 'ERROR'}</b>\n"
        f"{'🟢' if state['telegram_ok'] else '🔴'} Telegram: "
        f"<b>{'CONNECTED' if state['telegram_ok'] else 'ERROR'}</b>\n"
        f"{'🟢' if state['xau_ok'] else '🔴'} XAUUSD: "
        f"<b>{'OK' if state['xau_ok'] else 'ERROR'}</b>\n"
        f"{'🟢' if state['nas_ok'] else '🔴'} NAS100: "
        f"<b>{'OK' if state['nas_ok'] else 'ERROR'}</b>\n\n"
        f"⏱️ Last scan: {state['last_scan'] or '—'}\n"
        f"🟢 Last success: {state['last_success'] or '—'}\n"
        f"📨 Last signal: {state['last_signal'] or '—'}\n"
        f"⏳ Uptime: {hours}h {minutes}m\n"
    )

    if state["last_error"]:
        text += f"\n⚠️ <b>Last error:</b>\n{state['last_error'][:500]}"

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await health_command(update, context)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "health":
        await health_command(update, context)
    elif query.data == "signals":
        await query.edit_message_text(
            "📡 <b>SIGNAL ENGINE ACTIVE</b>\n\n"
            "The bot sends only qualifying BUY/SELL setups.\n"
            "No WAIT messages are generated.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(),
        )
    elif query.data == "xau":
        await query.edit_message_text(
            f"🥇 <b>XAUUSD</b>\n\n"
            f"Symbol: {XAU_SYMBOL}\n"
            f"Entry TF: {ENTRY_INTERVAL}\n"
            f"Mode: STRAIGHT + SLINGSHOT",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(),
        )
    elif query.data == "nas":
        await query.edit_message_text(
            f"📈 <b>NAS100</b>\n\n"
            f"Symbol: {NAS_SYMBOL}\n"
            f"Entry TF: {ENTRY_INTERVAL}\n"
            f"Mode: STRAIGHT + SLINGSHOT",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(),
        )

# ---------------- SCANNER ----------------

async def scan_symbol(application, symbol):
    # Sequential requests deliberately reduce API pressure.
    c5, _ = await asyncio.to_thread(fetch_candles, symbol, ENTRY_INTERVAL, 120)
    c15, _ = await asyncio.to_thread(fetch_candles, symbol, MAIN_INTERVAL, 120)
    c1h, _ = await asyncio.to_thread(fetch_candles, symbol, HTF_INTERVAL, 120)

    signal = build_signal(symbol, c5, c15, c1h)

    if symbol == XAU_SYMBOL:
        state["xau_ok"] = True
    elif symbol == NAS_SYMBOL:
        state["nas_ok"] = True

    return signal

async def scanner_loop(application):
    state["scanner_running"] = True
    log.info("Signal scanner started")

    while True:
        cycle_ok = False

        try:
            state["last_scan"] = utc_now()

            # XAU first
            try:
                signal = await scan_symbol(application, XAU_SYMBOL)
                cycle_ok = True
                if signal:
                    await process_signal(application, signal)
            except Exception as exc:
                state["xau_ok"] = False
                state["last_error"] = f"XAU: {exc}"
                log.exception("XAU scan failed")

            # Small gap to reduce rate-limit pressure.
            await asyncio.sleep(2)

            # NAS second
            try:
                signal = await scan_symbol(application, NAS_SYMBOL)
                cycle_ok = True
                if signal:
                    await process_signal(application, signal)
            except Exception as exc:
                state["nas_ok"] = False
                state["last_error"] = f"NAS: {exc}"
                log.exception("NAS scan failed")

            if cycle_ok:
                state["last_success"] = utc_now()
                state["scanner_errors"] = 0
            else:
                state["scanner_errors"] += 1

        except asyncio.CancelledError:
            state["scanner_running"] = False
            raise
        except Exception as exc:
            state["scanner_errors"] += 1
            state["last_error"] = f"Scanner: {exc}"
            log.exception("Scanner loop recovered from unexpected error")
            await asyncio.sleep(10)

        await asyncio.sleep(SCAN_SECONDS)

async def process_signal(application, signal):
    key = signal_key(signal)
    now = time.time()

    # Same signal/candle cannot be sent repeatedly.
    if key in signal_memory and now - signal_memory[key] < SIGNAL_COOLDOWN_SECONDS:
        return

    # Also suppress a duplicate setup on the same symbol within cooldown.
    simple_key = (signal["symbol"], signal["setup"])
    if simple_key in signal_memory and now - signal_memory[simple_key] < SIGNAL_COOLDOWN_SECONDS:
        return

    signal_memory[key] = now
    signal_memory[simple_key] = now

    state["last_signal"] = f"{signal['setup']} {signal['symbol']}"
    state["last_signal_time"] = now

    log.info("QUALIFYING SIGNAL: %s", state["last_signal"])
    await send_text(application, format_signal(signal))

# ---------------- WATCHDOG ----------------

async def watchdog_loop(application):
    """
    Keeps a lightweight watchdog alive.
    It does not generate WAIT messages.
    """
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_SECONDS)

            if not state["scanner_running"]:
                log.warning("Scanner appears stopped; restarting.")
                state["scanner_running"] = True
                asyncio.create_task(scanner_loop(application))

            # Remove old signal-memory entries.
            cutoff = time.time() - SIGNAL_COOLDOWN_SECONDS * 3
            old = [k for k, v in signal_memory.items() if v < cutoff]
            for k in old:
                signal_memory.pop(k, None)

        except asyncio.CancelledError:
            return
        except Exception as exc:
            log.exception("Watchdog error: %s", exc)
            await asyncio.sleep(10)

# ---------------- STARTUP ----------------

async def post_init(application):
    await application.bot.set_my_commands([
        ("start", "Open signal terminal"),
        ("health", "Check bot health"),
        ("status", "Check bot status"),
    ])

    state["telegram_ok"] = True

    if TELEGRAM_CHAT_ID:
        await send_text(
            application,
            "🟢 <b>KING OF XAU/NAS ONLINE</b>\n\n"
            "Signal engine: <b>ACTIVE</b>\n"
            "Mode: <b>STRAIGHT + SLINGSHOT</b>\n"
            "Notifications: <b>SIGNAL ONLY</b>\n\n"
            "Use /health anytime to check the scanner."
        )

    asyncio.create_task(scanner_loop(application))
    asyncio.create_task(watchdog_loop(application))

def validate_config():
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TWELVE_DATA_API_KEY:
        missing.append("TWELVE_DATA_API_KEY")

    if missing:
        raise RuntimeError("Missing Render environment variables: " + ", ".join(missing))

def main():
    validate_config()

    threading.Thread(target=run_web, daemon=True).start()

    log.info("Starting KING OF XAU/NAS...")
    log.info("XAU_SYMBOL=%s | NAS_SYMBOL=%s", XAU_SYMBOL, NAS_SYMBOL)
    log.info("ENTRY=%s | MAIN=%s | HTF=%s", ENTRY_INTERVAL, MAIN_INTERVAL, HTF_INTERVAL)

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("health", health_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(callback_handler))

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )

if __name__ == "__main__":
    main()
