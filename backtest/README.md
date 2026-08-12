# NQ1! Open (ORB) strategy backtester

Backtests an Opening Range Breakout strategy — the first N minutes of the
session define a range, and the first close outside that range triggers a
trade — against 30 days of intraday data.

There's no free continuous NQ1! (Nasdaq-100 E-mini futures) feed, so by
default this pulls **QQQ** (Nasdaq-100 ETF) 5m candles from Yahoo Finance
as a proxy: same index, same regular session hours (9:30–16:00 ET), free
and no API key needed. Swap in real NQ1! data any time with `--data-file`.

## Quick start

```bash
cd backtest
python3 run_backtest.py --days 30
```

This fetches fresh data, runs the strategy, prints a report, and writes:
- `results/<symbol>_orb_trades.csv` — every trade taken
- `results/<symbol>_orb_equity_curve.csv` — equity after each trade

## Using your own NQ1! data

If you have a real NQ1! export (from TradingView, your broker, etc.),
convert it to a CSV with these columns and point the backtester at it:

```
timestamp_utc,open,high,low,close,volume
2026-07-14T13:30:00+00:00,716.20,717.05,715.90,716.67,120345
...
```

```bash
python3 run_backtest.py --data-file /path/to/your_nq1_5m.csv --tz America/New_York
```

## Strategy parameters

| Flag | Default | Meaning |
|---|---|---|
| `--opening-range-minutes` | 5 | Length of the opening range |
| `--reward-risk` | 2.0 | Take-profit as a multiple of risk (1:2 default) |
| `--position-size-pct` | 100 | % of equity notionally sized per trade |
| `--fee-pct` | 0.05 | Round-trip commission/slippage assumption |
| `--starting-equity` | 10000 | Starting account size for the equity curve |

Stop-loss is always the opposite side of the opening range. Only the first
breakout each day is traded; if neither the stop nor target is hit, the
trade closes at the session's last candle (EOD exit).

## Files

- `fetch_data.py` — pulls intraday candles from Yahoo Finance, saves CSV
- `orb_strategy.py` — the ORB entry/exit rules, turns candles into trades
- `engine.py` — turns trades into an equity curve + win rate / drawdown / profit factor stats
- `run_backtest.py` — CLI entry point that wires the above together
