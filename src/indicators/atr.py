"""Wilder's ATR (Average True Range).

Implements the classic Wilder smoothing, as specified for Dao Gam V1
(`docs/DAO_GAM_RULES.md` Section 3 rule 4 / rule 7, `docs/DATA_SCHEMA.md`
Section 5 `atr_h1_14`).

This module only computes the indicator from an OHLC(V) DataFrame that
already conforms to `docs/DATA_SCHEMA.md` Section 1 (columns `high`,
`low`, `close`, and optionally `open`). It does not know about zones,
sweeps, or signals.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["high", "low", "close"]


def _validate_period(period: int) -> None:
    if not isinstance(period, int) or isinstance(period, bool):
        raise TypeError(f"period must be an int, got {type(period).__name__}")
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required column(s): {missing}")

    for col in REQUIRED_COLUMNS:
        if df[col].isna().any():
            bad_idx = df.index[df[col].isna()].tolist()
            raise ValueError(f"column '{col}' contains NaN at row(s) {bad_idx}")

    high, low, close = df["high"], df["low"], df["close"]

    # Per docs/DATA_SCHEMA.md Section 1: high >= max(open, close, low),
    # low <= min(open, close, high). 'open' is optional for ATR itself, but
    # if present it must still be internally consistent.
    checks = [high >= low, high >= close, low <= close]
    if "open" in df.columns:
        if df["open"].isna().any():
            bad_idx = df.index[df["open"].isna()].tolist()
            raise ValueError(f"column 'open' contains NaN at row(s) {bad_idx}")
        checks.append(high >= df["open"])
        checks.append(low <= df["open"])

    invalid = ~np.logical_and.reduce(checks)
    if invalid.any():
        bad_idx = df.index[invalid].tolist()
        raise ValueError(f"invalid OHLC (high/low/close inconsistent) at row(s) {bad_idx}")


def true_range(df: pd.DataFrame) -> pd.Series:
    """Wilder True Range.

    TR[0] = high[0] - low[0] (no previous close to compare against).
    TR[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    for i >= 1.
    """
    _validate_ohlc(df)

    if len(df) == 0:
        return pd.Series(dtype="float64", index=df.index, name="true_range")

    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)

    range_hl = high - low
    range_hc = (high - prev_close).abs()
    range_lc = (low - prev_close).abs()

    tr = pd.concat([range_hl, range_hc, range_lc], axis=1).max(axis=1)
    tr.iloc[0] = range_hl.iloc[0]
    tr.name = "true_range"
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ATR.

    - Rows before the first ATR value are NaN.
    - If there are fewer than `period` rows, the whole Series is NaN.
    - ATR at index `period - 1` = simple average of the first `period` TR
      values.
    - ATR at index `i > period - 1` = (prior_atr * (period - 1) + tr[i]) / period.
    """
    _validate_period(period)
    tr = true_range(df)

    result = pd.Series(np.nan, index=df.index, dtype="float64", name=f"atr_{period}")

    if len(df) < period:
        return result

    first_atr = tr.iloc[:period].mean()
    result.iloc[period - 1] = first_atr

    prior = first_atr
    for i in range(period, len(df)):
        current_tr = tr.iloc[i]
        prior = (prior * (period - 1) + current_tr) / period
        result.iloc[i] = prior

    return result
