#!/usr/bin/env python3
"""
Downloads intraday OHLCV candles from Yahoo Finance's public chart API and
saves them as CSV.

Yahoo Finance has no real "NQ1!" (Nasdaq-100 E-mini continuous futures)
feed available for free, so this defaults to QQQ (Nasdaq-100 ETF) as a
liquid, highly-correlated proxy that trades the same session hours. Pass
--symbol to use something else, or skip this script entirely and point
run_backtest.py at your own CSV via --data-file.

Usage:
    python3 fetch_data.py --symbol QQQ --interval 5m --days 30 --out data/qqq_5m.csv
"""

import argparse
import csv
import datetime as dt
import os

import requests

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# Yahoo blocks requests with no User-Agent header.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; backtest-script/1.0)"}


def fetch_intraday(symbol, interval="5m", days=30):
    """Fetch up to `days` days of `interval` candles for `symbol` from Yahoo Finance."""
    # Yahoo's intraday history is capped (60d for 5m/15m, 30d for 1m) regardless
    # of the requested range, so clamp to what it actually supports.
    range_days = min(days, 59) if interval != "1m" else min(days, 7)
    resp = requests.get(
        YAHOO_CHART_URL.format(symbol=symbol),
        params={"interval": interval, "range": f"{range_days}d"},
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()

    result = payload.get("chart", {}).get("result")
    if not result:
        err = payload.get("chart", {}).get("error")
        raise RuntimeError(f"Yahoo Finance returned no data for {symbol}: {err}")

    result = result[0]
    timestamps = result.get("timestamp")
    if not timestamps:
        raise RuntimeError(f"Yahoo Finance returned no candles for {symbol}")

    quote = result["indicators"]["quote"][0]
    opens, highs, lows, closes, volumes = (
        quote["open"], quote["high"], quote["low"], quote["close"], quote["volume"],
    )

    tz_name = result["meta"].get("exchangeTimezoneName", "America/New_York")

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    rows = []
    for i, ts in enumerate(timestamps):
        if None in (opens[i], highs[i], lows[i], closes[i]):
            continue  # Yahoo pads gaps (halts, thin pre/post market) with nulls
        candle_time = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
        if candle_time < cutoff:
            continue
        rows.append(
            {
                "timestamp_utc": candle_time.isoformat(),
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i] or 0,
            }
        )
    return rows, tz_name


def save_csv(rows, out_path):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp_utc", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Fetch intraday candles from Yahoo Finance")
    parser.add_argument("--symbol", default="QQQ", help="Ticker to fetch (default: QQQ, a Nasdaq-100 proxy for NQ1!)")
    parser.add_argument("--interval", default="5m", help="Candle interval, e.g. 1m, 5m, 15m (default: 5m)")
    parser.add_argument("--days", type=int, default=30, help="How many days of history to fetch (default: 30)")
    parser.add_argument("--out", default=None, help="Output CSV path (default: data/<symbol>_<interval>.csv)")
    args = parser.parse_args()

    out_path = args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", f"{args.symbol.lower()}_{args.interval}.csv"
    )

    rows, tz_name = fetch_intraday(args.symbol, args.interval, args.days)
    save_csv(rows, out_path)
    print(f"Saved {len(rows)} {args.interval} candles for {args.symbol} ({tz_name} session) -> {out_path}")


if __name__ == "__main__":
    main()
