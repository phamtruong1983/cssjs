"""Fractal swing high/low detection.

Implements the fractal swing definition used for Dao Gam V1's
support/resistance zones (`docs/DAO_GAM_RULES.md` Section 3 rule 3 /
Section 2, `docs/DATA_SCHEMA.md` Section 4 `zone_center`): a swing high at
position `i` is a bar whose `high` is greater than the `high` of the `n`
bars immediately before it AND greater than the `high` of the `n` bars
immediately after it (symmetric definition for swing low on `low`, with
`<`).

Neither `docs/DAO_GAM_RULES.md` nor `docs/DATA_SCHEMA.md` specifies how to
handle ties (equal highs/lows within the window) or whether a single bar
may be both a swing high and a swing low. Both are left to implementation
per `DAO_GAM_RULES.md` Section 3 rule 3's note ("does not need separate
approval"). This module's choices are documented as ASSUMPTIONS below.

ASSUMPTIONS (not specified in the docs, decided here):
  - Tie handling: strict inequality on both sides. A bar at `i` is a swing
    high only if `high[i] > high[j]` for every `j` in the `n`-bar window on
    each side -- a tie (equal high) anywhere in the window disqualifies
    `i`. Symmetric (`low[i] < low[j]`) for swing lows. This means a
    perfectly flat run of bars produces no swing points at all, which is
    the intended, conservative behavior for a strict-inequality rule.
  - A single bar CAN be both a swing high and a swing low at the same
    time (`is_swing_high` and `is_swing_low` are independent booleans);
    the docs do not prohibit this.

LOOK-AHEAD WARNING: `is_swing_high[i]` / `is_swing_low[i]` require the `n`
bars AFTER `i` to already exist and be closed. In other words, the swing
at index `i` cannot be known until bar `i + n` has closed. A caller
(e.g. the future zone/signal engine) must never treat a swing at `i` as
known before `i + n`. See `test_no_lookahead_swing_confirmed_only_after_n_bars`
in `tests/unit/test_swings.py` for the exact guarantee this module
provides: computing on data truncated at `i + n` yields the same swing
flags at `i` as computing on the full dataset.
"""
from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ["high", "low"]


def _validate_n(n: int) -> None:
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError(f"n must be an int, got {type(n).__name__}")
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required column(s): {missing}")

    for col in REQUIRED_COLUMNS:
        if df[col].isna().any():
            bad_idx = df.index[df[col].isna()].tolist()
            raise ValueError(f"column '{col}' contains NaN at row(s) {bad_idx}")

    high, low = df["high"], df["low"]
    invalid = high < low
    if invalid.any():
        bad_idx = df.index[invalid].tolist()
        raise ValueError(f"invalid OHLC: high < low at row(s) {bad_idx}")


def find_swings(df: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    """Detect fractal swing highs/lows.

    Parameters
    ----------
    df : DataFrame with at least `high` and `low` columns.
    n : bars required on each side (default 3, per Dao Gam V1 rule 3).

    Returns
    -------
    DataFrame with the same index as `df` and two boolean columns:
    `is_swing_high`, `is_swing_low`. The first `n` and last `n` rows are
    always False (insufficient bars on one side). If `len(df) < 2*n + 1`,
    every row is False (no position can have `n` bars on both sides).

    Raises
    ------
    TypeError / ValueError on an invalid `n`, missing `high`/`low`
    columns, NaN in either column, or `high < low` anywhere.
    """
    _validate_n(n)
    _validate_ohlc(df)

    is_swing_high = pd.Series(False, index=df.index, name="is_swing_high")
    is_swing_low = pd.Series(False, index=df.index, name="is_swing_low")

    length = len(df)
    if length < 2 * n + 1:
        return pd.DataFrame({"is_swing_high": is_swing_high, "is_swing_low": is_swing_low})

    high = df["high"].to_numpy()
    low = df["low"].to_numpy()

    for i in range(n, length - n):
        window_high = high[i - n : i + n + 1]
        window_low = low[i - n : i + n + 1]

        # Strict inequality on both sides (see module docstring ASSUMPTIONS):
        # bar i must be strictly greater/less than every other bar in the
        # window, not just the ones on one side.
        if high[i] == window_high.max() and (window_high == window_high.max()).sum() == 1:
            is_swing_high.iloc[i] = True
        if low[i] == window_low.min() and (window_low == window_low.min()).sum() == 1:
            is_swing_low.iloc[i] = True

    return pd.DataFrame({"is_swing_high": is_swing_high, "is_swing_low": is_swing_low})
