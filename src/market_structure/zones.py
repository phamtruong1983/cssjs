"""Support/resistance zones anchored on confirmed fractal swings.

Builds directly on `find_swings` (`src/market_structure/swings.py`) per
`docs/DAO_GAM_RULES.md` Section 3 rule 3 and `docs/DATA_SCHEMA.md`
Section 4: a zone is a **band**, `[zone_center - zone_width/2,
zone_center + zone_width/2]`, anchored on a single confirmed fractal
swing (`zone_center` = the swing's price -- `low` for a support anchor,
`high` for a resistance anchor). This module does not reimplement swing
detection; it only turns confirmed swings into zone bands and counts
touches.

CHỐNG LOOK-AHEAD / no-look-ahead: `create_zones(df, as_of, ...)` truncates
the input to rows `0 .. as_of` (inclusive) BEFORE calling `find_swings`,
so no row after `as_of` is ever read. Because `find_swings` itself only
flags a swing at position `i` once it has `n` bars on both sides within
the data it was given, truncating at `as_of` automatically restricts
confirmed swings to exactly those with `i + n <= as_of` -- there is no
separate "confirmed" filter layered on top; truncation is the single
mechanism that enforces it. This also guarantees, by construction, that
`create_zones(df, as_of=k)` on the full dataset equals
`create_zones(df.iloc[:k+1], as_of=k)` on data pre-truncated at `k`.

ASSUMPTIONS (not specified in docs/DAO_GAM_RULES.md or
docs/DATA_SCHEMA.md, decided here):

  - `zone_width` default: **1.00** (absolute price units, matching
    `docs/DATA_SCHEMA.md` Section 4's documented fixture convention).
    This is an implementation/fixture choice, explicitly **not** a
    `[V1_DECISION]` -- `DAO_GAM_RULES.md` Section 3 rule 3 leaves the
    exact value open and states no separate approval is required.
  - Touch comparison and float noise: prices and zone bounds are rounded
    to the nearest tick (`TICK = 0.01`, matching `docs/DATA_SCHEMA.md`
    Section 3 `tick_size` for XAUUSD) before the inclusive
    `zone_low <= price <= zone_high` comparison, to avoid spurious
    false/true results from binary floating-point representation of
    decimal prices (e.g. `1999.5000000000002`).
  - `touch_count` includes the anchor swing itself as one touch (matches
    `tests/fixtures/01_buy_valid/README.md`: the zone anchored at idx 5
    or idx 17, both `low = 2000.00`, is reported with `touch_count = 2`
    for `touch_idxs = [5, 17]` -- i.e. anchor + 1 other swing = 2, not
    anchor + other = potentially miscounted as something else).
  - **No merging/deduplication across anchors**: per the caller's
    explicit rule 6/7, every confirmed swing on a given side is its own
    anchor and produces its own zone row, even when two anchors share
    the same price and therefore produce byte-identical bands. This
    module never collapses two such rows into one. See the "open
    questions" note in this module's test file for the resulting
    multi-row behavior when several swings sit at the same level.
  - `side` column: neither `docs/DAO_GAM_RULES.md` nor
    `docs/DATA_SCHEMA.md` defines a field name enumerating support vs.
    resistance (unlike `direction`, which Section 6 fixes to
    `"buy"`/`"sell"`). This module uses `side` with values
    `"support"` (anchored on a swing low) / `"resistance"` (anchored on
    a swing high).
  - `anchor_idx` / `touch_idxs` are **positional** (0-based row position
    within `df`, matching how `tests/fixtures/*/README.md` describe
    "idx N"), not `df.index` labels. If `df` carries a non-default index
    (e.g. a `DatetimeIndex`), positions are still reported as plain
    integers 0..len(df)-1.
  - A zone is only returned if `touch_count >= min_touches`; invalid
    zones are omitted entirely from the result (never included with a
    flag), per the caller's explicit rule 2.
"""
from __future__ import annotations

import pandas as pd

from .swings import find_swings

TICK = 0.01
DEFAULT_WIDTH = 1.00
DEFAULT_MIN_TOUCHES = 2

RESULT_COLUMNS = [
    "side",
    "anchor_idx",
    "zone_center",
    "zone_low",
    "zone_high",
    "zone_width",
    "touch_count",
    "touch_idxs",
]


def _round_tick(x: float) -> float:
    return round(round(x / TICK) * TICK, 10)


def _validate_as_of(as_of: int, length: int) -> None:
    if not isinstance(as_of, int) or isinstance(as_of, bool):
        raise TypeError(f"as_of must be an int, got {type(as_of).__name__}")
    if as_of < 0:
        raise ValueError(f"as_of must be >= 0, got {as_of}")


def _validate_width(width: float) -> None:
    if isinstance(width, bool) or not isinstance(width, (int, float)):
        raise TypeError(f"width must be a number, got {type(width).__name__}")
    if width <= 0:
        raise ValueError(f"width must be > 0, got {width}")


def _validate_min_touches(min_touches: int) -> None:
    if not isinstance(min_touches, int) or isinstance(min_touches, bool):
        raise TypeError(f"min_touches must be an int, got {type(min_touches).__name__}")
    if min_touches < 1:
        raise ValueError(f"min_touches must be >= 1, got {min_touches}")


def create_zones(
    df: pd.DataFrame,
    as_of: int,
    n: int = 3,
    width: float = DEFAULT_WIDTH,
    min_touches: int = DEFAULT_MIN_TOUCHES,
) -> pd.DataFrame:
    """Build support/resistance zones from swings confirmed by `as_of`.

    Parameters
    ----------
    df : DataFrame with at least `high` and `low` columns (validated by
        `find_swings`).
    as_of : positional index (0-based) of the last closed bar the caller
        is allowed to know about. Only swings with `anchor_idx + n <=
        as_of` can anchor a zone. No row of `df` after position `as_of`
        is ever read (see module docstring).
    n : bars required on each side for a fractal swing (default 3,
        forwarded to `find_swings`).
    width : absolute-price zone width (default 1.00; see module
        docstring ASSUMPTIONS -- not a `[V1_DECISION]`).
    min_touches : minimum touch count (including the anchor) for a zone
        to be considered valid (default 2, per
        `docs/DAO_GAM_RULES.md` Section 3 rule 3).

    Returns
    -------
    DataFrame (default RangeIndex, one row per anchor) with columns
    `side`, `anchor_idx`, `zone_center`, `zone_low`, `zone_high`,
    `zone_width`, `touch_count`, `touch_idxs`. Only VALID zones
    (`touch_count >= min_touches`) are included; there is no row for an
    invalid candidate. Empty (0-row, correctly-typed) DataFrame if no
    zone qualifies.

    Raises
    ------
    TypeError / ValueError on invalid `as_of`, `width`, `min_touches`, or
    (via `find_swings`) invalid `n`, missing `high`/`low` columns, NaN,
    or `high < low`.
    """
    _validate_as_of(as_of, len(df))
    _validate_width(width)
    _validate_min_touches(min_touches)

    truncated = df.iloc[: as_of + 1]
    swings = find_swings(truncated, n=n)

    high = truncated["high"].to_numpy()
    low = truncated["low"].to_numpy()

    high_swing_positions = [i for i in range(len(truncated)) if bool(swings["is_swing_high"].iloc[i])]
    low_swing_positions = [i for i in range(len(truncated)) if bool(swings["is_swing_low"].iloc[i])]

    rows = []

    for side, positions, prices in (
        ("resistance", high_swing_positions, high),
        ("support", low_swing_positions, low),
    ):
        for anchor_pos in positions:
            center = float(prices[anchor_pos])
            zone_low = _round_tick(center - width / 2)
            zone_high = _round_tick(center + width / 2)

            touch_idxs = [
                p
                for p in positions
                if zone_low <= _round_tick(float(prices[p])) <= zone_high
            ]
            touch_count = len(touch_idxs)

            if touch_count >= min_touches:
                rows.append(
                    {
                        "side": side,
                        "anchor_idx": anchor_pos,
                        "zone_center": center,
                        "zone_low": zone_low,
                        "zone_high": zone_high,
                        "zone_width": float(width),
                        "touch_count": touch_count,
                        "touch_idxs": sorted(touch_idxs),
                    }
                )

    if not rows:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    return pd.DataFrame(rows, columns=RESULT_COLUMNS)
