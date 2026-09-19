"""Fetch OHLCV price data for the Dao Gam tool.

Uses yfinance (free, no API key) as the default data source. FX tickers on
Yahoo Finance use the "<BASE><QUOTE>=X" convention, e.g. EURUSD=X, GBPUSD=X,
USDJPY=X. Index/commodity CFDs like US30 aren't on Yahoo under that name;
use "^DJI" for the Dow Jones cash index as a stand-in, or point load_csv at
your broker's exported history instead.
"""
from __future__ import annotations

import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]


def load_yfinance(symbol: str, interval: str = "1h", period: str = "730d") -> pd.DataFrame:
    """Download OHLCV history from Yahoo Finance.

    yfinance limits intraday intervals to the last ~730 days.
    """
    import yfinance as yf

    df = yf.download(symbol, interval=interval, period=period, progress=False, auto_adjust=False)
    if df.empty:
        raise ValueError(f"No data returned for {symbol!r} (interval={interval!r})")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[COLUMNS]
    df.index.name = "time"
    return df


def load_csv(path: str, tz: str | None = None) -> pd.DataFrame:
    """Load OHLCV history from a CSV file.

    Expected columns (case-insensitive): time/date, open, high, low, close,
    volume (volume optional -> filled with 0 if missing).
    """
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    time_col = next(c for c in df.columns if c in ("time", "date", "datetime"))
    df[time_col] = pd.to_datetime(df[time_col])
    df = df.set_index(time_col).sort_index()
    df.index.name = "time"
    if tz:
        df.index = df.index.tz_localize(tz)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df[COLUMNS]
