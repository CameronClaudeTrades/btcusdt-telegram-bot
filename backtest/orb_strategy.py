#!/usr/bin/env python3
"""
"NQ1! Open" strategy = classic Opening Range Breakout (ORB).

Rules
-----
1. Each trading day, the first `opening_range_minutes` of candles after the
   session open define the "opening range": range_high / range_low.
2. Wait for the first candle after the opening range whose CLOSE breaks
   outside that range.
   - close > range_high  -> go LONG
   - close < range_low   -> go SHORT
   Only the first breakout of the day is traded (one trade per day, max).
3. Stop-loss = the opposite side of the opening range.
4. Take-profit = entry +/- (reward_risk * risk), where risk = |entry - stop|.
5. If neither stop nor target is hit by session close, the trade is closed
   at the last candle's close (EOD exit).

Within a single candle, if both the stop and the target are inside its
high/low, the stop is assumed to fill first (conservative assumption -
these are 5m bars, not tick data, so we can't know the true intra-candle
order).
"""

from collections import defaultdict
from zoneinfo import ZoneInfo


def _to_local_days(candles, tz_name):
    """Group candles by local trading date, sorted chronologically within each day."""
    tz = ZoneInfo(tz_name)
    by_day = defaultdict(list)
    for c in candles:
        local_dt = c["dt_utc"].astimezone(tz)
        by_day[local_dt.date()].append((local_dt, c))
    for day in by_day:
        by_day[day].sort(key=lambda x: x[0])
    return dict(sorted(by_day.items()))


def generate_trades(candles, tz_name, opening_range_minutes=5, candle_minutes=5,
                     reward_risk=2.0, session_start_hhmm=(9, 30)):
    """
    candles: list of dicts with dt_utc (datetime, tz-aware UTC), open, high, low, close.
    Returns a list of trade dicts, one per trading day that produced a breakout.
    """
    range_candles = max(1, opening_range_minutes // candle_minutes)
    by_day = _to_local_days(candles, tz_name)

    trades = []
    for day, day_candles in by_day.items():
        if len(day_candles) <= range_candles:
            continue

        session_start = day_candles[0][0]
        expected_start = session_start.replace(
            hour=session_start_hhmm[0], minute=session_start_hhmm[1], second=0, microsecond=0
        )
        # Skip half/irregular sessions where the first candle isn't near the normal open,
        # since the "opening range" only means something relative to the real session open.
        if abs((session_start - expected_start).total_seconds()) > candle_minutes * 60:
            continue

        opening = day_candles[:range_candles]
        rest = day_candles[range_candles:]

        range_high = max(c["high"] for _, c in opening)
        range_low = min(c["low"] for _, c in opening)

        direction = None
        entry_idx = None
        for idx, (_, c) in enumerate(rest):
            if c["close"] > range_high:
                direction = "LONG"
                entry_idx = idx
                break
            if c["close"] < range_low:
                direction = "SHORT"
                entry_idx = idx
                break

        if direction is None:
            continue

        entry_dt, entry_candle = rest[entry_idx]
        entry_price = entry_candle["close"]

        if direction == "LONG":
            stop = range_low
            risk = entry_price - stop
            target = entry_price + reward_risk * risk
        else:
            stop = range_high
            risk = stop - entry_price
            target = entry_price - reward_risk * risk

        if risk <= 0:
            continue  # degenerate opening range (shouldn't happen, but guard anyway)

        exit_price, exit_dt, exit_reason = None, None, None
        for later_dt, c in rest[entry_idx + 1:]:
            if direction == "LONG":
                hit_stop = c["low"] <= stop
                hit_target = c["high"] >= target
            else:
                hit_stop = c["high"] >= stop
                hit_target = c["low"] <= target

            if hit_stop and hit_target:
                exit_price, exit_dt, exit_reason = stop, later_dt, "STOP"
                break
            if hit_stop:
                exit_price, exit_dt, exit_reason = stop, later_dt, "STOP"
                break
            if hit_target:
                exit_price, exit_dt, exit_reason = target, later_dt, "TARGET"
                break

        if exit_price is None:
            exit_dt, last_candle = day_candles[-1]
            exit_price, exit_reason = last_candle["close"], "EOD"

        pnl_pct = (exit_price - entry_price) / entry_price if direction == "LONG" else (entry_price - exit_price) / entry_price
        r_multiple = pnl_pct * entry_price / risk if risk else 0.0

        trades.append(
            {
                "date": str(day),
                "direction": direction,
                "range_high": range_high,
                "range_low": range_low,
                "entry_time": entry_dt.isoformat(),
                "entry_price": entry_price,
                "stop": stop,
                "target": target,
                "exit_time": exit_dt.isoformat(),
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "pnl_pct": pnl_pct,
                "r_multiple": r_multiple,
            }
        )

    return trades
