"""OHLCV structural validation for Dao Gam V1 fixtures.

This is schema/data validation only -- it knows nothing about zones,
sweeps, ATR, or signals. It exists to check that a CSV conforms to
docs/DATA_SCHEMA.md before any of that logic is built.
"""
from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ["timestamp", "symbol", "timeframe", "open", "high", "low", "close"]
OPTIONAL_COLUMNS = ["volume"]


def validate_ohlcv(df: pd.DataFrame) -> list[str]:
    """Return a list of schema-violation messages; empty list = valid.

    Per docs/DATA_SCHEMA.md:
      - required columns must be present (volume is optional)
      - timestamp must be strictly increasing, no duplicates
      - OHLC must be internally consistent (high is the max, low is the min)
      - volume, if present, may be missing (NaN) or 0 -- never invalid
    """
    errors: list[str] = []

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        errors.append(f"missing required column(s): {missing}")
        return errors  # can't check anything else meaningfully

    if df.empty:
        return errors

    ts = pd.to_datetime(df["timestamp"])
    if not ts.is_monotonic_increasing:
        errors.append("timestamp column is not strictly increasing")
    elif ts.duplicated().any():
        errors.append("timestamp column has duplicate values")

    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    bad_high = df.index[(h < o) | (h < c) | (h < l)]
    bad_low = df.index[(l > o) | (l > c) | (l > h)]
    for idx in sorted(set(bad_high) | set(bad_low)):
        errors.append(
            f"row {idx}: invalid OHLC (open={o[idx]}, high={h[idx]}, "
            f"low={l[idx]}, close={c[idx]})"
        )

    if "volume" in df.columns:
        vol = df["volume"]
        negative = df.index[vol.notna() & (vol < 0)]
        for idx in negative:
            errors.append(f"row {idx}: negative volume ({vol[idx]})")

    return errors
