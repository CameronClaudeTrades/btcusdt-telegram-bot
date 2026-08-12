#!/usr/bin/env python3
"""
Backtest the "NQ1! Open" (Opening Range Breakout) strategy over the last N
days of intraday data.

No free NQ1! (Nasdaq-100 E-mini continuous futures) feed exists, so by
default this fetches QQQ (Nasdaq-100 ETF) 5m candles from Yahoo Finance as
a proxy -- same index exposure, same regular session hours. Swap in your
own NQ1! export any time with --data-file (see the CSV format note below).

Usage
-----
  # Fetch fresh QQQ data and backtest the last 30 days:
  python3 run_backtest.py --days 30

  # Use your own data file instead of fetching (columns: timestamp_utc,open,high,low,close,volume):
  python3 run_backtest.py --data-file my_nq1_5m.csv --tz America/New_York

  # Tweak strategy parameters:
  python3 run_backtest.py --days 30 --opening-range-minutes 15 --reward-risk 3
"""

import argparse
import csv
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import run_backtest
from fetch_data import fetch_intraday, save_csv
from orb_strategy import generate_trades

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def load_csv(path):
    candles = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            candles.append(
                {
                    "dt_utc": dt.datetime.fromisoformat(row["timestamp_utc"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or 0),
                }
            )
    candles.sort(key=lambda c: c["dt_utc"])
    return candles


def print_report(stats, trades, symbol, args):
    print("=" * 60)
    print(f"NQ1! Open (ORB) strategy backtest — proxy symbol: {symbol}")
    print(f"Opening range: {args.opening_range_minutes}m | Reward:Risk 1:{args.reward_risk} | "
          f"Position size: {args.position_size_pct}% | Fee/slippage: {args.fee_pct}% per trade")
    print("=" * 60)
    print(f"Trades taken:        {stats['num_trades']}  (long {stats['long_trades']} / short {stats['short_trades']})")
    print(f"Win rate:            {stats['win_rate_pct']:.1f}%  ({stats['num_wins']}W / {stats['num_losses']}L)")
    print(f"Avg R multiple:      {stats['avg_r_multiple']:.2f}R")
    print(f"Avg win / avg loss:  {stats['avg_win_pct']:.2f}% / {stats['avg_loss_pct']:.2f}%")
    pf = stats["profit_factor"]
    print(f"Profit factor:       {'inf' if pf == float('inf') else f'{pf:.2f}'}")
    print(f"Max drawdown:        {stats['max_drawdown_pct']:.2f}%")
    print(f"Starting equity:     ${stats['starting_equity']:,.2f}")
    print(f"Final equity:        ${stats['final_equity']:,.2f}")
    print(f"Total return:        {stats['total_return_pct']:+.2f}%")
    print("=" * 60)

    if trades:
        print("\nTrade log:")
        print(f"{'Date':<11}{'Dir':<6}{'Entry':<10}{'Exit':<10}{'Reason':<8}{'PnL%':<8}{'R':<6}")
        for t in trades:
            print(
                f"{t['date']:<11}{t['direction']:<6}{t['entry_price']:<10.2f}{t['exit_price']:<10.2f}"
                f"{t['exit_reason']:<8}{t['net_pnl_pct']*100:<8.2f}{t['r_multiple']:<6.2f}"
            )
    else:
        print("\nNo qualifying breakout trades in this window.")


def save_results(trades, equity_curve, stats, symbol):
    os.makedirs(RESULTS_DIR, exist_ok=True)

    trades_path = os.path.join(RESULTS_DIR, f"{symbol.lower()}_orb_trades.csv")
    with open(trades_path, "w", newline="") as f:
        if trades:
            writer = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
            writer.writeheader()
            writer.writerows(trades)
        else:
            f.write("")

    equity_path = os.path.join(RESULTS_DIR, f"{symbol.lower()}_orb_equity_curve.csv")
    with open(equity_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "equity"])
        writer.writeheader()
        writer.writerows(equity_curve)

    print(f"\nSaved trade log   -> {trades_path}")
    print(f"Saved equity curve -> {equity_path}")


def main():
    parser = argparse.ArgumentParser(description="Backtest the NQ1! Open (ORB) strategy")
    parser.add_argument("--symbol", default="QQQ", help="Ticker to fetch if --data-file is not given (default: QQQ)")
    parser.add_argument("--interval", default="5m", help="Candle interval (default: 5m)")
    parser.add_argument("--days", type=int, default=30, help="Days of history to backtest (default: 30)")
    parser.add_argument("--data-file", default=None, help="Use this CSV instead of fetching (columns: timestamp_utc,open,high,low,close,volume)")
    parser.add_argument("--tz", default=None, help="Session timezone for --data-file (default: auto from Yahoo Finance, or America/New_York)")
    parser.add_argument("--opening-range-minutes", type=int, default=5, help="Opening range length in minutes (default: 5)")
    parser.add_argument("--reward-risk", type=float, default=2.0, help="Take-profit as a multiple of risk (default: 2.0 = 1:2)")
    parser.add_argument("--position-size-pct", type=float, default=100.0, help="Percent of equity notionally sized per trade (default: 100)")
    parser.add_argument("--fee-pct", type=float, default=0.05, help="Round-trip fee/slippage percent per trade (default: 0.05)")
    parser.add_argument("--starting-equity", type=float, default=10_000.0, help="Starting account equity (default: 10000)")
    args = parser.parse_args()

    candle_minutes = int("".join(ch for ch in args.interval if ch.isdigit()) or 5)

    if args.data_file:
        candles = load_csv(args.data_file)
        tz_name = args.tz or "America/New_York"
        symbol = args.symbol
    else:
        print(f"Fetching {args.days}d of {args.interval} candles for {args.symbol} from Yahoo Finance...")
        rows, tz_name = fetch_intraday(args.symbol, args.interval, args.days)
        if not rows:
            print("No data returned - nothing to backtest.")
            return
        cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", f"{args.symbol.lower()}_{args.interval}.csv")
        save_csv(rows, cache_path)
        print(f"Cached {len(rows)} candles -> {cache_path}")
        candles = [
            {
                "dt_utc": dt.datetime.fromisoformat(r["timestamp_utc"]),
                "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"],
            }
            for r in rows
        ]
        symbol = args.symbol

    trades_raw = generate_trades(
        candles,
        tz_name=tz_name,
        opening_range_minutes=args.opening_range_minutes,
        candle_minutes=candle_minutes,
        reward_risk=args.reward_risk,
    )

    trades, equity_curve, stats = run_backtest(
        trades_raw,
        starting_equity=args.starting_equity,
        position_size_pct=args.position_size_pct,
        fee_pct=args.fee_pct,
    )

    print_report(stats, trades, symbol, args)
    save_results(trades, equity_curve, stats, symbol)


if __name__ == "__main__":
    main()
