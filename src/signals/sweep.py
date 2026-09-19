"""H1 sweep/trap candle detection for a single, caller-supplied zone.

Implements the mechanical part of `docs/DAO_GAM_RULES.md` Section 3 rules
4 and 5 (sweep candle + trap confirmation) and Section 3 rule 7's ATR
reference, for exactly one H1 candle (`idx`) tested against exactly one
zone. This module does not select which zone to test (that is a future
engine's job) and does not call `create_zones` -- the caller passes the
zone's `side`/`zone_low`/`zone_center`/`zone_high` directly.

ATR REFERENCE, `[idx-1]` NOT `[idx]`: every threshold in this module uses
`atr.iloc[idx - 1]` -- the ATR value as of the close of the bar BEFORE the
sweep candle, never `atr.iloc[idx]` (which would already fold in the
sweep candle's own, typically huge, True Range). This matches
`tests/fixtures/01_buy_valid/README.md`'s documented `atr_h1_14 = 10.00`
for the sweep candle at idx 22, which is `atr.iloc[21]` under standard
Wilder ATR (see `tests/unit/test_atr.py::test_atr_matches_fixture_01_documented_value`
for the same reasoning applied to the ATR module itself). If `idx < 1` or
`atr.iloc[idx - 1]` is NaN, this function does not raise -- it returns a
not-a-trap result with `reason = "atr_unavailable"`.

CHỐNG LOOK-AHEAD / no-look-ahead: only `df` row `idx` and `atr.iloc[idx - 1]`
are ever read. No other row of `df` or `atr` is inspected, so changing
data after `idx` cannot change the result.

Field names follow `docs/DATA_SCHEMA.md` Sections 4-6 where a field of
that name exists there (`sweep_extreme`, `h1_range`, `pierce_depth`,
`atr_h1_14`, `zone_low`, `zone_center`, `zone_high`, `direction`).
`range_multiple`, `range_ok`, `pierce_ok`, `closed_back_inside`, `is_trap`,
and `reason` are not defined in `docs/DATA_SCHEMA.md`; they are this
module's own result fields (see ASSUMPTIONS below).

ASSUMPTIONS (not specified in the docs, decided here):
  - `direction`: `"buy"` for a `support` zone, `"sell"` for a
    `resistance` zone, matching `docs/DATA_SCHEMA.md` Section 6's
    `direction` enum (`"buy"`/`"sell"`) and Section 3 rule 4's
    support-vs-resistance framing.
  - Threshold comparisons are `>=` and inclusive of the boundary exactly
    as rule 4 states ("must be >= 1.5 x ATR(14)", "must pierce ... by
    >= 0.25 x ATR(14)"), and the "close back inside the zone" check
    (rule 5) is inclusive of `zone_low`/`zone_high` themselves, matching
    `docs/DATA_SCHEMA.md` Section 4's touch definition, which is also
    stated as an inclusive `[zone_low, zone_high]` band.
  - Float/tick rounding: `h1_range`, `pierce_depth`, and `close` are
    rounded to the nearest tick (`TICK`, imported from
    `src.market_structure.zones` -- the same public constant `create_zones`
    uses, not a private helper) before every threshold comparison, to
    avoid spurious pass/fail from binary floating-point noise.
  - `reason` codes (short, deliberately distinct from any status name in
    `docs/DAO_GAM_RULES.md` Section 6 / `docs/DATA_SCHEMA.md` Section 8 --
    this module never assigns a pipeline status, only a local mechanical
    reason): `"ok"` (is_trap True), `"atr_unavailable"`, `"range_fail"`,
    `"pierce_fail"`, `"not_closed_back_inside"`. When more than one
    condition fails, `reason` reports the first failing condition in the
    order range -> pierce -> closed-back-inside (documented, not
    significant beyond that -- all three boolean flags are always
    returned regardless of which failed first).
  - Per `docs/DAO_GAM_RULES.md` Section 2 / Section 6 "Not a named
    status" note: a candle that satisfies range and pierce but does not
    close back inside the zone is `is_trap = False` with
    `range_ok = True`, `pierce_ok = True`, `closed_back_inside = False`,
    and `reason = "not_closed_back_inside"` -- this is a local mechanical
    reason code, not one of the pipeline's named statuses
    (`NEEDS_MANUAL_REVIEW` / `REJECTED_M15_NO_REACTION` / `EXPIRED` /
    `REJECTED_RR_BELOW_THRESHOLD`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from src.market_structure.zones import TICK

VALID_SIDES = ("support", "resistance")
REQUIRED_COLUMNS = ["high", "low", "close"]


@dataclass
class SweepResult:
    is_trap: bool
    direction: str
    sweep_extreme: float
    h1_range: float
    range_multiple: float
    pierce_depth: float
    atr_h1_14: float
    zone_low: float
    zone_center: float
    zone_high: float
    range_ok: bool
    pierce_ok: bool
    closed_back_inside: bool
    reason: str


def _round_tick(x: float) -> float:
    return round(round(x / TICK) * TICK, 10)


def _validate_zone(zone: Mapping) -> tuple[str, float, float, float]:
    for key in ("side", "zone_low", "zone_center", "zone_high"):
        if key not in zone:
            raise ValueError(f"zone missing required key: {key!r}")

    side = zone["side"]
    if side not in VALID_SIDES:
        raise ValueError(f"side must be one of {VALID_SIDES}, got {side!r}")

    zone_low = float(zone["zone_low"])
    zone_center = float(zone["zone_center"])
    zone_high = float(zone["zone_high"])

    if not (zone_low < zone_center < zone_high):
        raise ValueError(
            f"zone bounds must satisfy zone_low < zone_center < zone_high, "
            f"got zone_low={zone_low}, zone_center={zone_center}, zone_high={zone_high}"
        )

    return side, zone_low, zone_center, zone_high


def _validate_idx(idx: int, length: int) -> None:
    if not isinstance(idx, int) or isinstance(idx, bool):
        raise TypeError(f"idx must be an int, got {type(idx).__name__}")
    if idx < 0 or idx >= length:
        raise ValueError(f"idx must be in [0, {length - 1}], got {idx}")


def _validate_bar(df: pd.DataFrame, idx: int) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required column(s): {missing}")

    row = df.iloc[idx]
    for col in REQUIRED_COLUMNS:
        if pd.isna(row[col]):
            raise ValueError(f"column '{col}' is NaN at idx {idx}")

    if row["high"] < row["low"]:
        raise ValueError(f"invalid OHLC: high < low at idx {idx}")


def detect_sweep(df: pd.DataFrame, atr: pd.Series, idx: int, zone: Mapping) -> SweepResult:
    """Test whether H1 bar `idx` is a sweep/trap candle against `zone`.

    Parameters
    ----------
    df : H1 OHLC DataFrame (at least `high`, `low`, `close` columns).
    atr : ATR Series aligned to `df`'s positions (e.g. from
        `src.indicators.atr.atr`). Only `atr.iloc[idx - 1]` is read.
    idx : positional (0-based) index of the candidate sweep candle.
    zone : mapping with `side` (`"support"`/`"resistance"`), `zone_low`,
        `zone_center`, `zone_high`. Not selected or computed here -- the
        caller decides which zone to test.

    Returns
    -------
    SweepResult. See module docstring for field semantics and the
    `reason` codes.

    Raises
    ------
    TypeError / ValueError on invalid `idx`, missing `high`/`low`/`close`
    columns, NaN at row `idx`, `high < low` at row `idx`, an invalid
    `zone` (missing key, bad `side`, or bounds not `zone_low <
    zone_center < zone_high`).
    """
    _validate_idx(idx, len(df))
    _validate_bar(df, idx)
    side, zone_low, zone_center, zone_high = _validate_zone(zone)

    direction = "buy" if side == "support" else "sell"

    row = df.iloc[idx]
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])

    sweep_extreme = low if side == "support" else high

    h1_range = _round_tick(high - low)

    if idx < 1 or pd.isna(atr.iloc[idx - 1]):
        return SweepResult(
            is_trap=False,
            direction=direction,
            sweep_extreme=sweep_extreme,
            h1_range=h1_range,
            range_multiple=float("nan"),
            pierce_depth=float("nan"),
            atr_h1_14=float("nan"),
            zone_low=zone_low,
            zone_center=zone_center,
            zone_high=zone_high,
            range_ok=False,
            pierce_ok=False,
            closed_back_inside=False,
            reason="atr_unavailable",
        )

    atr_h1_14 = float(atr.iloc[idx - 1])
    range_multiple = h1_range / atr_h1_14

    range_ok = h1_range >= _round_tick(1.5 * atr_h1_14)

    if side == "support":
        pierce_depth = _round_tick(zone_low - low)
    else:
        pierce_depth = _round_tick(high - zone_high)
    pierce_ok = pierce_depth >= _round_tick(0.25 * atr_h1_14)

    closed_back_inside = _round_tick(zone_low) <= _round_tick(close) <= _round_tick(zone_high)

    is_trap = range_ok and pierce_ok and closed_back_inside

    if not range_ok:
        reason = "range_fail"
    elif not pierce_ok:
        reason = "pierce_fail"
    elif not closed_back_inside:
        reason = "not_closed_back_inside"
    else:
        reason = "ok"

    return SweepResult(
        is_trap=is_trap,
        direction=direction,
        sweep_extreme=sweep_extreme,
        h1_range=h1_range,
        range_multiple=range_multiple,
        pierce_depth=pierce_depth,
        atr_h1_14=atr_h1_14,
        zone_low=zone_low,
        zone_center=zone_center,
        zone_high=zone_high,
        range_ok=range_ok,
        pierce_ok=pierce_ok,
        closed_back_inside=closed_back_inside,
        reason=reason,
    )
