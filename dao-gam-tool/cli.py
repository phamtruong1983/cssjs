"""Command-line entry point for the Dao Gam FX signal tool.

Examples
--------
Scan and backtest EURUSD H1 using free Yahoo Finance data:

    python cli.py --symbol EURUSD=X --interval 1h --period 730d --backtest

Scan a local CSV export (e.g. from your broker/MT4) for the latest signals:

    python cli.py --csv my_h1_data.csv --last 5
"""
from __future__ import annotations

import argparse

import pandas as pd

from backtest import run_backtest, summarize
from dao_gam import find_signals, signals_to_frame
import data as data_mod


def main() -> None:
    parser = argparse.ArgumentParser(description="Dao Gam (dagger) FX stop-hunt signal scanner")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--symbol", help="Yahoo Finance ticker, e.g. EURUSD=X, GBPUSD=X, ^DJI")
    src.add_argument("--csv", help="Path to a local OHLCV CSV file")

    parser.add_argument("--interval", default="1h", help="yfinance interval (default: 1h)")
    parser.add_argument("--period", default="730d", help="yfinance period (default: 730d, its intraday max)")

    parser.add_argument("--swing-lookback", type=int, default=3)
    parser.add_argument("--atr-period", type=int, default=14)
    parser.add_argument("--min-pierce-atr", type=float, default=0.25)
    parser.add_argument("--reject-close-atr", type=float, default=0.15)
    parser.add_argument("--stop-buffer-atr", type=float, default=0.2)

    parser.add_argument("--last", type=int, default=10, help="how many most recent signals to print")
    parser.add_argument("--backtest", action="store_true", help="also run the simple bar-by-bar backtest")

    args = parser.parse_args()

    if args.symbol:
        df = data_mod.load_yfinance(args.symbol, interval=args.interval, period=args.period)
    else:
        df = data_mod.load_csv(args.csv)

    signals = find_signals(
        df,
        swing_lookback=args.swing_lookback,
        atr_period=args.atr_period,
        min_pierce_atr=args.min_pierce_atr,
        reject_close_atr=args.reject_close_atr,
        stop_buffer_atr=args.stop_buffer_atr,
    )

    frame = signals_to_frame(signals)
    pd.set_option("display.width", 160)
    print(f"Found {len(signals)} Dao Gam signal(s).")
    if not frame.empty:
        print(frame.tail(args.last))

    if args.backtest and signals:
        results = run_backtest(df, signals)
        print("\nBacktest results (per signal):")
        print(results.tail(args.last))
        print("\nSummary:")
        for k, v in summarize(results).items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
