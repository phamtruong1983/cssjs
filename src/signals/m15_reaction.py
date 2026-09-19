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
the **open** time of the bar. At most 4 candles are evaluated, in
chronological order; scanning **stops at the first candle that fires**
(fewer than 4 candles are evaluated/logged if the reaction fires early).

Per-candle fields use the exact names from `docs/DATA_SCHEMA.md` Section
7: `body_size`, `candle_range`, `close_position_in_range`,
`reaction_fired`. `m15_index_in_window` is 1-based, per that section.
`body_ratio` (`body_size / candle_range`) is not a named field in
`docs/DATA_SCHEMA.md` -- it is an intermediate value used only to check
condition b) from `DAO_GAM_RULES.md` Section 4, kept on the per-candle
record for transparency (see ASSUMPTIONS).

BUY conditions (`DAO_GAM_RULES.md` Section 4, "BUY case"), all required:
  a) close > zone_center (strict)
  b) body_ratio >= 0.30
  c) close_position_in_range >= 0.60

SELL conditions (mirror, "SELL case"), all required:
  a) close < zone_center (strict)
  b) body_ratio >= 0.30
  c) close_position_in_range <= 0.40

ASSUMPTIONS (not specified in the docs, decided here):
  - `body_ratio` is included on each per-candle record as a convenience
    (it is exactly `body_size / candle_range`, both of which ARE named
    schema fields), even though `docs/DATA_SCHEMA.md` does not name it.
  - Timestamps are parsed and compared in UTC via `pandas.to_datetime(...,
    utc=True)`, accepting both ISO strings (with or without a trailing
    "Z") and native datetime/Timestamp objects, per `docs/DATA_SCHEMA.md`
    Section 2.
  - No status is assigned here (per the caller's instruction not to add
    new statuses) -- the result's `outcome` field is a local value,
    either `"reaction_fired"` or `"no_reaction"`, not one of the
    pipeline's named statuses (`NEEDS_MANUAL_REVIEW` /
    `REJECTED_M15_NO_REACTION` / `EXPIRED` / `REJECTED_RR_BELOW_THRESHOLD`).
    Mapping `"no_reaction"` to `REJECTED_M15_NO_REACTION` is a future
    engine's job, not this module's.
  - If a candle's `candle_range` is `0` (a bar with `high == low`),
    `body_ratio` and `close_position_in_range` are both undefined
    (division by zero); this module treats such a candle as not firing
    (`reaction_fired = False`) rather than raising, recording `nan` for
    both ratio fields, since the docs do not address this edge case.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

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
    reaction_fired: bool


@dataclass
class M15ReactionResult:
    outcome: str  # "reaction_fired" | "no_reaction"
    reaction_fired: bool
    fired_index: int | None
    fired_timestamp: pd.Timestamp | None
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


def _validate_row(row: pd.Series) -> None:
    for col in ("open", "high", "low", "close"):
        if pd.isna(row[col]):
            raise ValueError(f"column '{col}' is NaN at timestamp {row['timestamp']}")
    if row["high"] < row["low"]:
        raise ValueError(f"invalid OHLC: high < low at timestamp {row['timestamp']}")


def _condition_met(direction: str, close: float, zone_center: float, body_ratio: float, close_pos: float) -> bool:
    if pd.isna(body_ratio) or pd.isna(close_pos):
        return False
    if direction == "buy":
        return close > zone_center and body_ratio >= 0.30 and close_pos >= 0.60
    return close < zone_center and body_ratio >= 0.30 and close_pos <= 0.40


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
        columns (M15 bars). Only rows whose timestamp falls in the
        confirmation window are read/validated.
    sweep_h1_open : the sweep H1 candle's open-time timestamp (ISO string,
        with or without trailing "Z", or a datetime/Timestamp). Parsed to
        UTC.
    direction : `"buy"` or `"sell"`.
    zone_center : the zone's center price (float).

    Returns
    -------
    M15ReactionResult with `outcome` (`"reaction_fired"` /
    `"no_reaction"`), `reaction_fired`, `fired_index` /
    `fired_timestamp` (`None` if no reaction), and `candles` -- the list
    of `M15Candle` records actually evaluated (scanning stops at the
    first firing candle, so fewer than 4 may be present).

    Raises
    ------
    ValueError on an invalid `direction`, missing required columns, NaN
    in `open`/`high`/`low`/`close` for any candle inside the window, or
    `high < low` for any candle inside the window.
    """
    _validate_direction(direction)
    _validate_columns(m15_df)

    sweep_open_ts = pd.to_datetime(sweep_h1_open, utc=True)
    window_start = sweep_open_ts + pd.Timedelta(hours=1)
    window_end = sweep_open_ts + pd.Timedelta(hours=2)

    df = m15_df.copy()
    df["_ts"] = pd.to_datetime(df["timestamp"], utc=True)
    in_window = df[(df["_ts"] >= window_start) & (df["_ts"] < window_end)].sort_values("_ts")
    in_window = in_window.head(MAX_WINDOW_CANDLES)

    candles: list[M15Candle] = []
    fired_index = None
    fired_timestamp = None
    reaction_fired = False

    for position, (_, row) in enumerate(in_window.iterrows(), start=1):
        _validate_row(row)

        open_, high, low, close = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        body_size = abs(close - open_)
        candle_range = high - low

        if candle_range == 0:
            body_ratio = float("nan")
            close_pos = float("nan")
        else:
            body_ratio = body_size / candle_range
            close_pos = (close - low) / candle_range

        fired = _condition_met(direction, close, zone_center, body_ratio, close_pos)

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
                reaction_fired=fired,
            )
        )

        if fired:
            reaction_fired = True
            fired_index = position
            fired_timestamp = row["_ts"]
            break

    outcome = "reaction_fired" if reaction_fired else "no_reaction"

    return M15ReactionResult(
        outcome=outcome,
        reaction_fired=reaction_fired,
        fired_index=fired_index,
        fired_timestamp=fired_timestamp,
        direction=direction,
        zone_center=float(zone_center),
        window_start=window_start,
        window_end=window_end,
        candles=candles,
    )
