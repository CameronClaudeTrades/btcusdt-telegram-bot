#!/usr/bin/env python3
"""
BTCUSDT setup alert bot -> sends a Telegram message whenever your
long/short confluence rules line up.

STRATEGY (as specified)
------------------------
LONG:
  1. On the 5m chart: 10 EMA crosses ABOVE 30 EMA (golden cross), AND price
     closes outside the upper Bollinger Band (20, 2std) within 40 minutes
     (8 x 5m candles) of that cross.
  2. On the 15m chart: 10 EMA is above 30 EMA (trend agrees).
  3. Price is above the 200 EMA.  <-- ASSUMPTION: evaluated on the 15m
     chart (not specified in the brief). Change EMA200_TIMEFRAME below if
     you meant the 5m chart instead.

SHORT: mirror image (death cross + lower band break, 15m 30>10, price < 200EMA)

On a valid signal it sends a Telegram message with entry, stop-loss,
take-profit and position size, based on:
  - Stop-loss distance: 0.4%  (ASSUMPTION: "SL is 0.4" read as 0.4%)
  - Reward:Risk = 1:4
  - Position size = 40% of account (informational only, not auto-traded)

This script does NOT place any trades. It only reads public market data
and sends you a Telegram message.

SETUP
-----
1. pip install requests
2. Fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID below.
3. Run it: python3 btcusdt_setup_bot.py
   It polls every 60s and only evaluates once a new 5m candle closes.
   Keep it running 24/7 on a machine/server/VPS of your choice (see
   README.md for free hosting options) -- this script has no scheduler
   built in, it just loops.
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

# ----------------------------------------------------------------------
# CONFIG - set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID as environment
# variables (e.g. Railway service variables). Falls back to the literal
# strings below only if you're running this locally and prefer to hardcode.
# ----------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PASTE_YOUR_CHAT_ID_HERE")

SYMBOL = "BTCUSDT"
EMA_FAST = 10
EMA_SLOW = 30
EMA_TREND = 200
BB_LENGTH = 20
BB_STD = 2

CROSS_BREAKOUT_WINDOW_MIN = 40          # confirm BB break within this many minutes of the cross
CROSS_BREAKOUT_WINDOW_CANDLES = CROSS_BREAKOUT_WINDOW_MIN // 5  # on the 5m chart -> 8 candles

EMA200_TIMEFRAME = "15m"                # ASSUMPTION - change to "5m" if that's what you meant

STOP_LOSS_PCT = 0.004                   # 0.4%
REWARD_RISK = 4                         # 1:4
POSITION_SIZE_PCT = 40                  # informational only

POLL_SECONDS = 60
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.json")

BASE_URLS = ["https://data-api.binance.vision", "https://api.binance.com"]

# ----------------------------------------------------------------------
# Data fetching
# ----------------------------------------------------------------------

def fetch_klines(interval, limit=300):
    last_err = None
    for base in BASE_URLS:
        try:
            r = requests.get(
                f"{base}/api/v3/klines",
                params={"symbol": SYMBOL, "interval": interval, "limit": limit},
                timeout=10,
            )
            r.raise_for_status()
            raw = r.json()
            return [
                {
                    "open_time": row[0],
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "close_time": row[6],
                }
                for row in raw
            ]
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError(f"Could not fetch klines for {interval}: {last_err}")


# ----------------------------------------------------------------------
# Indicators
# ----------------------------------------------------------------------

def ema(values, length):
    k = 2 / (length + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def bollinger_bands(values, length, num_std):
    upper, lower, basis = [None] * len(values), [None] * len(values), [None] * len(values)
    for i in range(length - 1, len(values)):
        window = values[i - length + 1: i + 1]
        mean = sum(window) / length
        var = sum((x - mean) ** 2 for x in window) / length
        std = var ** 0.5
        basis[i] = mean
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std
    return upper, lower, basis


# ----------------------------------------------------------------------
# State (dedup so we don't re-alert every poll for the same cross event)
# ----------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_long_cross_time": None, "last_short_cross_time": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ----------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    resp.raise_for_status()


# ----------------------------------------------------------------------
# Core detection logic
# ----------------------------------------------------------------------

def find_recent_cross_with_breakout(closes, ema_fast, ema_slow, upper_bb, lower_bb, direction):
    """
    direction: "long" (golden cross + upper band break) or "short" (death cross + lower band break)
    Returns (cross_idx, breakout_idx) of the most recent qualifying event within the lookback
    window, or (None, None).
    """
    n = len(closes)
    lookback_start = max(1, n - 1 - CROSS_BREAKOUT_WINDOW_CANDLES - CROSS_BREAKOUT_WINDOW_CANDLES)

    for cross_idx in range(n - 1, lookback_start - 1, -1):
        if ema_fast[cross_idx - 1] is None or ema_slow[cross_idx - 1] is None:
            continue
        prev_diff = ema_fast[cross_idx - 1] - ema_slow[cross_idx - 1]
        cur_diff = ema_fast[cross_idx] - ema_slow[cross_idx]

        is_golden = prev_diff <= 0 and cur_diff > 0
        is_death = prev_diff >= 0 and cur_diff < 0

        if direction == "long" and not is_golden:
            continue
        if direction == "short" and not is_death:
            continue

        window_end = min(n - 1, cross_idx + CROSS_BREAKOUT_WINDOW_CANDLES)
        for j in range(cross_idx, window_end + 1):
            if direction == "long" and upper_bb[j] is not None and closes[j] > upper_bb[j]:
                return cross_idx, j
            if direction == "short" and lower_bb[j] is not None and closes[j] < lower_bb[j]:
                return cross_idx, j

    return None, None


def evaluate():
    candles_5m = fetch_klines("5m", limit=300)
    candles_15m = fetch_klines("15m", limit=300)

    closes_5m = [c["close"] for c in candles_5m]
    ema10_5m = ema(closes_5m, EMA_FAST)
    ema30_5m = ema(closes_5m, EMA_SLOW)
    upper_bb, lower_bb, _ = bollinger_bands(closes_5m, BB_LENGTH, BB_STD)

    closes_15m = [c["close"] for c in candles_15m]
    ema10_15m = ema(closes_15m, EMA_FAST)
    ema30_15m = ema(closes_15m, EMA_SLOW)
    ema200_15m = ema(closes_15m, EMA_TREND)
    ema200_5m = ema(closes_5m, EMA_TREND)

    trend_ema200 = ema200_15m if EMA200_TIMEFRAME == "15m" else ema200_5m
    price = closes_5m[-1]

    state = load_state()
    alerts = []

    # ---- LONG ----
    cross_idx, breakout_idx = find_recent_cross_with_breakout(
        closes_5m, ema10_5m, ema30_5m, upper_bb, lower_bb, "long"
    )
    if cross_idx is not None:
        cross_time = candles_5m[cross_idx]["open_time"]
        confirms_15m = ema10_15m[-1] > ema30_15m[-1]
        confirms_200 = price > trend_ema200[-1]
        already_alerted = state.get("last_long_cross_time") == cross_time
        if confirms_15m and confirms_200 and not already_alerted:
            sl = price * (1 - STOP_LOSS_PCT)
            tp = price * (1 + STOP_LOSS_PCT * REWARD_RISK)
            alerts.append(("LONG", price, sl, tp, cross_time))
            state["last_long_cross_time"] = cross_time

    # ---- SHORT ----
    cross_idx, breakout_idx = find_recent_cross_with_breakout(
        closes_5m, ema10_5m, ema30_5m, upper_bb, lower_bb, "short"
    )
    if cross_idx is not None:
        cross_time = candles_5m[cross_idx]["open_time"]
        confirms_15m = ema10_15m[-1] < ema30_15m[-1]
        confirms_200 = price < trend_ema200[-1]
        already_alerted = state.get("last_short_cross_time") == cross_time
        if confirms_15m and confirms_200 and not already_alerted:
            sl = price * (1 + STOP_LOSS_PCT)
            tp = price * (1 - STOP_LOSS_PCT * REWARD_RISK)
            alerts.append(("SHORT", price, sl, tp, cross_time))
            state["last_short_cross_time"] = cross_time

    save_state(state)
    return alerts


def format_alert(direction, price, sl, tp, cross_time):
    ts = datetime.fromtimestamp(cross_time / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"*BTCUSDT {direction} setup*\n"
        f"Cross candle: {ts}\n"
        f"Entry (approx): {price:,.2f}\n"
        f"Stop loss ({STOP_LOSS_PCT*100:.1f}%): {sl:,.2f}\n"
        f"Take profit (1:{REWARD_RISK}): {tp:,.2f}\n"
        f"Suggested size: {POSITION_SIZE_PCT}% of account\n"
        f"Confluences: 5m {'golden' if direction=='LONG' else 'death'} cross + BB break "
        f"within {CROSS_BREAKOUT_WINDOW_MIN}m, 15m EMA trend agrees, price "
        f"{'above' if direction=='LONG' else 'below'} 200EMA ({EMA200_TIMEFRAME})."
    )


def main():
    print(f"Watching {SYMBOL}... polling every {POLL_SECONDS}s")
    last_checked_candle = None
    while True:
        try:
            candles_5m = fetch_klines("5m", limit=2)
            latest_open_time = candles_5m[-1]["open_time"]
            if latest_open_time != last_checked_candle:
                last_checked_candle = latest_open_time
                alerts = evaluate()
                for direction, price, sl, tp, cross_time in alerts:
                    msg = format_alert(direction, price, sl, tp, cross_time)
                    print(msg)
                    send_telegram(msg)
        except Exception as e:  # noqa: BLE001
            print(f"[{datetime.now(timezone.utc)}] error: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    if "PASTE_YOUR" in TELEGRAM_BOT_TOKEN or "PASTE_YOUR" in TELEGRAM_CHAT_ID:
        raise SystemExit("Fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID at the top of this file first.")
    main()
