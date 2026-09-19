"""Very simple bar-by-bar backtest for Dao Gam signals.

For each signal, walks forward from the signal bar and checks whether price
hits the stop, tp1, or tp2 first (using subsequent highs/lows). This is a
sanity-check backtest, not an execution-accurate simulator: it ignores
spread/slippage, assumes the entry fills exactly at `entry`, and resolves
same-bar stop/target hits pessimistically (stop first).
"""
from __future__ import annotations

import pandas as pd

from dao_gam import Signal


def evaluate_signal(df: pd.DataFrame, signal: Signal, max_bars: int = 200) -> dict:
    start = df.index.get_loc(signal.time) + 1
    end = min(start + max_bars, len(df))
    outcome = "open"
    exit_price = None
    exit_time = None

    for i in range(start, end):
        bar = df.iloc[i]
        if signal.direction == "buy":
            hit_stop = bar["low"] <= signal.stop
            hit_tp2 = bar["high"] >= signal.tp2
            hit_tp1 = bar["high"] >= signal.tp1
        else:
            hit_stop = bar["high"] >= signal.stop
            hit_tp2 = bar["low"] <= signal.tp2
            hit_tp1 = bar["low"] <= signal.tp1

        if hit_stop:
            outcome, exit_price, exit_time = "stop", signal.stop, df.index[i]
            break
        if hit_tp2:
            outcome, exit_price, exit_time = "tp2", signal.tp2, df.index[i]
            break
        if hit_tp1:
            outcome, exit_price, exit_time = "tp1", signal.tp1, df.index[i]
            break

    if outcome == "open":
        exit_price = df.iloc[end - 1]["close"]
        exit_time = df.index[end - 1]

    if signal.direction == "buy":
        pnl = exit_price - signal.entry
    else:
        pnl = signal.entry - exit_price
    r_multiple = pnl / signal.risk if signal.risk else float("nan")

    return {
        "time": signal.time,
        "direction": signal.direction,
        "entry": signal.entry,
        "stop": signal.stop,
        "tp1": signal.tp1,
        "tp2": signal.tp2,
        "outcome": outcome,
        "exit_price": exit_price,
        "exit_time": exit_time,
        "r_multiple": r_multiple,
    }


def run_backtest(df: pd.DataFrame, signals: list[Signal], max_bars: int = 200) -> pd.DataFrame:
    rows = [evaluate_signal(df, s, max_bars=max_bars) for s in signals]
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> dict:
    if results.empty:
        return {"trades": 0}
    closed = results[results["outcome"] != "open"]
    wins = closed[closed["r_multiple"] > 0]
    return {
        "trades": len(results),
        "closed": len(closed),
        "win_rate": round(len(wins) / len(closed), 3) if len(closed) else float("nan"),
        "avg_r": round(closed["r_multiple"].mean(), 3) if len(closed) else float("nan"),
        "expectancy_r": round(closed["r_multiple"].sum(), 3) if len(closed) else float("nan"),
        "outcome_counts": closed["outcome"].value_counts().to_dict(),
    }
