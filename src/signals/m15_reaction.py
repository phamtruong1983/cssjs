"""M15 reversal-reaction check for a confirmed H1 sweep candle.

Implements `docs/DAO_GAM_RULES.md` Section 4 (the M15 "reversal reaction"
definition) for exactly one H1 sweep candle and one caller-supplied
`zone_center` / `direction`. This module does not call `sweep.py` or
`zones.py` and does not select a zone -- the caller decides which sweep
candle and zone to test.

WINDOW: the M15 candles considered are those with (open-time) timestamp
in `[sweep_h1_open + 1h, sweep_h1_open + 2h)` -- i.e. the 4 M15 candles of
the H1 hour immediately AFTER the sweep candle's own hour, never the
sweep hour itself. Per `docs/DATA_SCHEMA.md` Section 2, timestamps mark
the **open** time of the bar. Rows are read in the order they appear in
`m15_df` (never re-sorted -- see VALIDATION below); at most the first 4
rows that fall in the window are evaluated. Scanning **stops at the
first candle that fires** (fewer than 4 may be evaluated/logged if the
reaction fires early).

OUTCOME (exactly 3 values -- caller does not tell this module whether the
window "should" have 4 candles or not, so it cannot distinguish a bar
missing to a data gap from one that simply hasn't printed yet; the caller
is responsible for only ever passing already-closed bars):
  - `"fired"` -- some evaluated candle satisfied all of a/b/c.
  - `"no_reaction"` -- exactly 4 candles were available in the window and
    none of them fired.
  - `"window_incomplete"` -- fewer than 4 candles were available in the
    window (0, 1, 2, or 3) and none of them fired.

TICK-INTEGER COMPARISON: to avoid binary floating-point noise (e.g.
`2000.8 - 2000.5` not being exactly `0.3`), every threshold comparison is
done in integer "ticks" using `TICK` imported from
`src.market_structure.zones` (the same public constant `create_zones`
and `sweep.py` use -- not a private helper). `t(x) = round(x / TICK)`.
  - `open_t, high_t, low_t, close_t = t(open), t(high), t(low), t(close)`
  - `body_t = abs(close_t - open_t)`, `range_t = high_t - low_t`,
    `pos_t = close_t - low_t`
  - b) `body_t * 10 >= 3 * range_t` (integer form of `body/range >= 0.30`)
  - BUY  c) `pos_t * 100 >= 60 * range_t`
  - SELL c) `pos_t * 100 <= 40 * range_t`
  - a) BUY: `close_t > zone_center_t`; SELL: `close_t < zone_center_t`
    (`zone_center_t = t(zone_center)`).
  - `range_t == 0` (a bar with `high == low`, in ticks): the candle
    cannot fire (`cond_b = cond_c = reaction_fired = False`); this is a
    special case, not "always true" (`body_t*10 >= 3*0` would otherwise
    be vacuously true for any `body_t >= 0`). `body_ratio` and
    `close_position_in_range` are still logged as `nan` in this case.

Per-candle fields use the exact names from `docs/DATA_SCHEMA.md` Section
7: `body_size`, `candle_range`, `close_position_in_range`,
`reaction_fired`. `m15_index_in_window` is 1-based, per that section.
`body_ratio`, `cond_a`, `cond_b`, `cond_c`, and the result's
`activation_h1_open` are not named fields in `docs/DATA_SCHEMA.md` (see
ASSUMPTIONS).

VALIDATION:
  - `zone_center` must be a finite number (not NaN/inf) -- raises
    `ValueError` otherwise.
  - Timestamps of the rows that fall in the window must be **strictly
    increasing in the order they appear in `m15_df`** -- this module
    never sorts by timestamp. A duplicate or out-of-order timestamp among
    window rows raises `ValueError`. NaN or invalid OHLC OUTSIDE the
    window never raises (only window rows are read/validated).

ASSUMPTIONS (not specified in the docs, decided here):
  - `activation_h1_open` = `sweep_h1_open + 1h` (i.e. `window_start`) when
    `outcome == "fired"`, else `None`. All 4 possible M15 candles in the
    window fall in the same H1 hour, so this value does not depend on
    which of the (up to 4) candles actually fired.
  - `cond_a`, `cond_b`, `cond_c` are per-candle booleans for conditions
    a/b/c respectively (independent of each other and of `range_t == 0`
    short-circuiting `cond_b`/`cond_c` to `False`), to make it possible to
    see exactly which condition(s) a candle failed.
  - No status is assigned here (per the caller's instruction not to add
    new statuses) -- `outcome` is a local value, not one of the
    pipeline's named statuses (`NEEDS_MANUAL_REVIEW` /
    `REJECTED_M15_NO_REACTION` / `EXPIRED` / `REJECTED_RR_BELOW_THRESHOLD`).
  - Timestamps are parsed and compared in UTC via `pandas.to_datetime(...,
    utc=True)`, accepting both ISO strings (with or without a trailing
    "Z") and native datetime/Timestamp objects, per `docs/DATA_SCHEMA.md`
    Section 2.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.market_structure.zones import TICK

VALID_DIRECTIONS = ("buy", "sell")
REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close"]
MAX_WINDOW_CANDLES = 4


@dataclass
class M15Candle:
    m15_index_in_window: int
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    body_size: float
    candle_range: float
    body_ratio: float
    close_position_in_range: float
    cond_a: bool
    cond_b: bool
    cond_c: bool
    reaction_fired: bool


@dataclass
class M15ReactionResult:
    outcome: str  # "fired" | "no_reaction" | "window_incomplete"
    reaction_fired: bool
    fired_index: int | None
    fired_timestamp: pd.Timestamp | None
    activation_h1_open: pd.Timestamp | None
    direction: str
    zone_center: float
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    candles: list = field(default_factory=list)


def _validate_direction(direction: str) -> None:
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {VALID_DIRECTIONS}, got {direction!r}")


def _validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required column(s): {missing}")


def _validate_zone_center(zone_center: float) -> float:
    value = float(zone_center)
    if not np.isfinite(value):
        raise ValueError(f"zone_center must be a finite number, got {zone_center!r}")
    return value


def _validate_row(row: pd.Series) -> None:
    for col in ("open", "high", "low", "close"):
        if pd.isna(row[col]):
            raise ValueError(f"column '{col}' is NaN at timestamp {row['timestamp']}")
    if row["high"] < row["low"]:
        raise ValueError(f"invalid OHLC: high < low at timestamp {row['timestamp']}")


def _tick(x: float) -> int:
    return round(x / TICK)


def check_m15_reaction(
    m15_df: pd.DataFrame,
    sweep_h1_open,
    direction: str,
    zone_center: float,
) -> M15ReactionResult:
    """Check the M15 reversal reaction for one H1 sweep candle.

    Parameters
    ----------
    m15_df : DataFrame with `timestamp`, `open`, `high`, `low`, `close`
        columns (M15 bars), in chronological row order. Only rows whose
        timestamp falls in the confirmation window are read/validated.
    sweep_h1_open : the sweep H1 candle's open-time timestamp (ISO string,
        with or without trailing "Z", or a datetime/Timestamp). Parsed to
        UTC.
    direction : `"buy"` or `"sell"`.
    zone_center : the zone's center price. Must be finite.

    Returns
    -------
    M15ReactionResult. See module docstring for `outcome` semantics,
    tick-integer comparisons, and validation rules.

    Raises
    ------
    ValueError on an invalid `direction`, a non-finite `zone_center`,
    missing required columns, a duplicate/out-of-order timestamp among
    window rows, NaN in `open`/`high`/`low`/`close` for any window
    candle, or `high < low` for any window candle.
    """
    _validate_direction(direction)
    _validate_columns(m15_df)
    zone_center = _validate_zone_center(zone_center)

    sweep_open_ts = pd.to_datetime(sweep_h1_open, utc=True)
    window_start = sweep_open_ts + pd.Timedelta(hours=1)
    window_end = sweep_open_ts + pd.Timedelta(hours=2)

    df = m15_df.copy()
    df["_ts"] = pd.to_datetime(df["timestamp"], utc=True)
    in_window = df[(df["_ts"] >= window_start) & (df["_ts"] < window_end)]  # preserves original row order
    in_window = in_window.head(MAX_WINDOW_CANDLES)

    zone_center_t = _tick(zone_center)

    candles: list[M15Candle] = []
    fired_index = None
    fired_timestamp = None
    reaction_fired = False
    prev_ts = None

    for position, (_, row) in enumerate(in_window.iterrows(), start=1):
        if prev_ts is not None and row["_ts"] <= prev_ts:
            raise ValueError(
                f"timestamps within the window must be strictly increasing in row order; "
                f"got {row['_ts']} after {prev_ts}"
            )
        prev_ts = row["_ts"]

        _validate_row(row)

        open_, high, low, close = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        body_size = abs(close - open_)
        candle_range = high - low

        open_t, high_t, low_t, close_t = _tick(open_), _tick(high), _tick(low), _tick(close)
        body_t = abs(close_t - open_t)
        range_t = high_t - low_t
        pos_t = close_t - low_t

        if direction == "buy":
            cond_a = close_t > zone_center_t
        else:
            cond_a = close_t < zone_center_t

        if range_t == 0:
            cond_b = False
            cond_c = False
            body_ratio = float("nan")
            close_pos = float("nan")
        else:
            cond_b = body_t * 10 >= 3 * range_t
            if direction == "buy":
                cond_c = pos_t * 100 >= 60 * range_t
            else:
                cond_c = pos_t * 100 <= 40 * range_t
            body_ratio = body_size / candle_range
            close_pos = (close - low) / candle_range

        fired = cond_a and cond_b and cond_c

        candles.append(
            M15Candle(
                m15_index_in_window=position,
                timestamp=row["_ts"],
                open=open_,
                high=high,
                low=low,
                close=close,
                body_size=body_size,
                candle_range=candle_range,
                body_ratio=body_ratio,
                close_position_in_range=close_pos,
                cond_a=cond_a,
                cond_b=cond_b,
                cond_c=cond_c,
                reaction_fired=fired,
            )
        )

        if fired:
            reaction_fired = True
            fired_index = position
            fired_timestamp = row["_ts"]
            break

    if reaction_fired:
        outcome = "fired"
        activation_h1_open = window_start
    elif len(in_window) >= MAX_WINDOW_CANDLES:
        outcome = "no_reaction"
        activation_h1_open = None
    else:
        outcome = "window_incomplete"
        activation_h1_open = None

    return M15ReactionResult(
        outcome=outcome,
        reaction_fired=reaction_fired,
        fired_index=fired_index,
        fired_timestamp=fired_timestamp,
        activation_h1_open=activation_h1_open,
        direction=direction,
        zone_center=zone_center,
        window_start=window_start,
        window_end=window_end,
        candles=candles,
    )
