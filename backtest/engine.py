#!/usr/bin/env python3
"""Turns a list of ORB trades into an equity curve and summary stats."""


def run_backtest(trades, starting_equity=10_000.0, position_size_pct=100.0, fee_pct=0.0):
    """
    position_size_pct: % of equity notionally risked per trade (informational
    sizing, same style as the live bot's POSITION_SIZE_PCT). 100% means the
    full account return moves 1:1 with pnl_pct each trade.
    fee_pct: round-trip commission/slippage assumption, e.g. 0.05 for 0.05%.
    """
    equity = starting_equity
    peak_equity = starting_equity
    max_drawdown_pct = 0.0

    equity_curve = [{"date": None, "equity": equity}]
    enriched_trades = []

    for t in trades:
        net_pnl_pct = t["pnl_pct"] * (position_size_pct / 100.0) - (fee_pct / 100.0)
        equity *= (1 + net_pnl_pct)
        peak_equity = max(peak_equity, equity)
        drawdown_pct = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0.0
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        enriched = dict(t)
        enriched["net_pnl_pct"] = net_pnl_pct
        enriched["equity_after"] = equity
        enriched_trades.append(enriched)
        equity_curve.append({"date": t["date"], "equity": equity})

    wins = [t for t in enriched_trades if t["net_pnl_pct"] > 0]
    losses = [t for t in enriched_trades if t["net_pnl_pct"] <= 0]

    gross_profit = sum(t["net_pnl_pct"] for t in wins)
    gross_loss = -sum(t["net_pnl_pct"] for t in losses)

    stats = {
        "starting_equity": starting_equity,
        "final_equity": equity,
        "total_return_pct": (equity / starting_equity - 1) * 100,
        "num_trades": len(enriched_trades),
        "num_wins": len(wins),
        "num_losses": len(losses),
        "win_rate_pct": (len(wins) / len(enriched_trades) * 100) if enriched_trades else 0.0,
        "avg_r_multiple": (sum(t["r_multiple"] for t in enriched_trades) / len(enriched_trades)) if enriched_trades else 0.0,
        "avg_win_pct": (sum(t["net_pnl_pct"] for t in wins) / len(wins) * 100) if wins else 0.0,
        "avg_loss_pct": (sum(t["net_pnl_pct"] for t in losses) / len(losses) * 100) if losses else 0.0,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0,
        "max_drawdown_pct": max_drawdown_pct,
        "long_trades": sum(1 for t in enriched_trades if t["direction"] == "LONG"),
        "short_trades": sum(1 for t in enriched_trades if t["direction"] == "SHORT"),
    }

    return enriched_trades, equity_curve, stats
