"""Dao Gam V1 signal pipeline orchestrator.

Connects modules 1-7 (`atr.py`, `swings.py`, `zones.py`, `sweep.py`,
`m15_reaction.py`, `risk_reward.py`, `entry_simulation.py`) into one
pipeline per `docs/DAO_GAM_RULES.md` and `docs/DATA_SCHEMA.md`. This
module does NOT reimplement any submodule's logic -- it only calls them
and carries their results forward. The one piece of business logic that
belongs to the engine itself (not any submodule) is described in ZONE
MERGING below.

PIPELINE (per `sweep_idx`), stopping at the first stage that cannot
proceed (`stage` records where it stopped; `status` is `None` unless the
stage produces a named pipeline status):

  a. `sweep_idx < 1` or `atr.iloc[sweep_idx-1]` not finite ->
     `stage="atr_unavailable"`, `status=None`.
  b. `zones = create_zones(h1_df, as_of=sweep_idx-1, n=n, width=zone_width,
     min_touches=min_touches)`, then ZONE MERGING (see below).
  c. `detect_sweep` for every merged zone; if none traps ->
     `stage="no_trap"`, `status=None` (all candidate zones + their sweep
     results are logged in `zone_candidates`). Otherwise pick the winning
     zone (see ZONE SELECTION below).
  d. `h1_df` must have a row at `sweep_idx + 1` whose timestamp equals
     `timestamp[sweep_idx] + 1h` exactly -- otherwise `stage=
     "activation_bar_missing"`, `status=None` (a data gap).
  e. `check_m15_reaction(m15_df, sweep_ts, direction, zone_center)`:
     `"no_reaction"` -> `status=REJECTED_M15_NO_REACTION`,
     `stage="m15_no_reaction"`; `"window_incomplete"` ->
     `stage="m15_window_incomplete"`, `status=None`; `"fired"` -> continue.
  f. `compute_risk_reward(h1_df, sweep_idx, direction, zone_center,
     sweep_extreme, atr_h1_14)` (`atr_h1_14` taken from the winning zone's
     `SweepResult`, never recomputed): `reason="rr_below_threshold"` ->
     `status=REJECTED_RR_BELOW_THRESHOLD`, `stage="rr_below_threshold"`;
     `reason="tp1_unavailable"` -> `stage="tp1_unavailable"`,
     `status=None` (NOT a new pipeline status -- see OPEN QUESTIONS);
     `reason="ok"` -> continue.
  g. `simulate_entry(h1_df, activation_idx=sweep_idx+1, direction, entry=
     zone_center, stop=<from step f>)`: `"expired"` -> `status=EXPIRED`,
     `stage="expired"`; `"filled"` -> `status=NEEDS_MANUAL_REVIEW`,
     `entry_state="filled"`, `stage="filled"`; `"window_incomplete"` ->
     `status=NEEDS_MANUAL_REVIEW`, `entry_state="pending"`,
     `stage="pending"`.

ZONE MERGING (engine's own rule, not any submodule's): `create_zones`
returns one row per confirmed swing anchor (`src/market_structure/zones.py`
docstring ASSUMPTIONS: "No merging/deduplication across anchors"). This
engine merges rows sharing the same `(side, zone_low, zone_high)` into a
single candidate zone: `anchor_idx` becomes the SMALLEST anchor_idx in
the group; `touch_count`/`touch_idxs` are taken from the group (identical
across the group, since they only depend on the shared band); a
`merged_rows` count records how many original rows were merged.

ZONE SELECTION (when more than one merged zone traps on the same
`sweep_idx`): highest `touch_count` first; tie-break by smallest
`abs(sweep-candle close - zone_center)`; tie-break again by largest
`anchor_idx`.

CHỐNG LOOK-AHEAD / no-look-ahead: the pipeline for `sweep_idx` only
depends on `h1_df` rows up to `sweep_idx + 3` (the entry-validity window
is `sweep_idx+2` and `sweep_idx+3`; the activation candle `sweep_idx+1`
itself is only checked for existence/timestamp, never read for
high/low/close touch logic) and M15 rows in the hour `[sweep_ts+1h,
sweep_ts+2h)` (the activation bar's hour). `atr` must already be
computed by the caller (this engine does not slice or recompute it).
Zones themselves are computed with `as_of=sweep_idx-1` (`create_zones`
never reads past that). No H1 row at or after `sweep_idx + 4`, and no
M15 row at or after `sweep_ts + 2h`, is ever read.

ASSUMPTIONS / OPEN QUESTIONS (not specified in the docs, decided here):
  - `tp1_unavailable` (from `compute_risk_reward`) is deliberately NOT
    mapped to any pipeline status -- the caller's instructions explicitly
    forbid adding a new status, and `docs/DATA_SCHEMA.md` Section 8 does
    not define one for this case either (it only names
    `NEEDS_MANUAL_REVIEW` / `REJECTED_M15_NO_REACTION` / `EXPIRED` /
    `REJECTED_RR_BELOW_THRESHOLD`). `stage="tp1_unavailable"`,
    `status=None` is the only representation; a future engine revision
    would need a documented decision (new status, or folding it into
    `REJECTED_RR_BELOW_THRESHOLD`, or something else) before this could
    change.
  - `rr1` (`docs/DATA_SCHEMA.md` Section 6) is not populated:
    `compute_risk_reward` only returns `reward_to_tp2`/`rr_to_tp2` (R:R to
    TP2, the only ratio the rules doc gates on) -- it does not compute
    TP1's own R:R. `EngineResult` has no `rr1` field because no submodule
    is the source of that value; adding it would mean this engine
    computing it itself, which is out of scope (engine does not
    recompute numbers).
  - `direction` for the winning zone is `"buy"` for a `support` zone,
    `"sell"` for a `resistance` zone (matches `sweep.py`'s own mapping,
    reused verbatim from `SweepResult.direction`, not recomputed).
  - Zone merging happens ONLY on `(side, zone_low, zone_high)` equality;
    it is unrelated to, and happens before, the trap/selection logic in
    steps (c).
  - `run_engine` computes ATR once (via `src.indicators.atr.atr`) over
    the whole `h1_df` and reuses it for every `sweep_idx` in range --
    consistent with "engine does not recompute per-candidate what can be
    computed once."
  - No cooldown / overlapping-signal suppression -- explicitly out of
    scope (backtest module's job).

DIAGNOSTIC-ONLY FIELD (added on top of the pipeline above; changes no
status/stage/routing decision): `stop_breached_in_activation_hour`. Once
M15 has fired (i.e. `rr_result.stop` is known, regardless of
`rr_result.reason`), this checks whether any M15 candle
`check_m15_reaction` logged (from the first candle up to and including
the one that fired) already touched the stop-loss level -- BUY: any
candle with `tick(low) <= tick(stop)`; SELL: any candle with
`tick(high) >= tick(stop)` (tick-integer comparison, `TICK` from
`src.market_structure.zones`). `None` if the pipeline never reached that
point (stopped earlier). This is purely informational -- it never
changes `status`, `stage`, or which branch the pipeline takes; a setup
can still end as `NEEDS_MANUAL_REVIEW` with this flag `True` (V1 does not
act on it). `run_engine` always includes this field (module 8b D4 --
no code change was needed: it is a plain `EngineResult` field and
`run_engine` returns `EngineResult` objects unchanged).

MODULE 8b -- ATR-RELATIVE ZONE WIDTH (`zone_width_atr`, `D1`): an
OPTIONAL parameter on `evaluate_sweep_candidate`/`run_engine`, appended
AFTER every existing parameter, default `None`. `None` (the default)
reproduces the exact prior behavior: `zone_width` (the absolute-price
parameter, default `1.00`) is passed to `create_zones` unchanged, and
`EngineResult.zone_width_mode` is `"absolute"`. When `zone_width_atr` is
not `None`, it OVERRIDES `zone_width` entirely (the absolute parameter is
ignored, and this is deliberate, not a bug): the effective width is
`zone_width_atr * atr.iloc[sweep_idx-1]` (the same already-closed ATR
`detect_sweep` itself gates on), rounded to the nearest whole tick via
`round(x / TICK)` (`TICK` from `src.market_structure.zones`), with a
floor of 1 tick, and `EngineResult.zone_width_mode` is `"atr"`. Either
way, the width actually used is recorded in `EngineResult.
zone_width_used`; both `zone_width_used`/`zone_width_mode` are `None`
only when the pipeline never reaches the zone-creation step at all
(`stage="atr_unavailable"` or a `range_prefilter` short-circuit) --
every stage from `create_zones` onward (including `"no_trap"`) has them
populated. `zone_width_atr` must be a finite real number `> 0` (not
`bool`); invalid values raise `TypeError` (wrong type, including `bool`)
or `ValueError` (non-finite or `<= 0`), checked unconditionally at the
top of `evaluate_sweep_candidate`, before any other stage runs.
`range_prefilter`'s own `1.5*atr` threshold check is unaffected by
`zone_width_atr` -- it is about the sweep candle's range, not the zone
band.

MODULE 8b -- `annotate_repeats` (`D2`): a public function,
`annotate_repeats(results: list[EngineResult]) -> list[EngineResult]`,
returning a NEW list of shallow-copied `EngineResult`s (never mutates its
input) with two extra flags set: `repeat_zone_within_24h` and
`repeat_zone_within_72h`. For a result with a non-`None` `status`, each
flag is `True` if some OTHER result earlier in the same input list (by
`sweep_ts`, strictly smaller -- never a later one) also has a non-`None`
`status`, the same `direction`, the same `zone_center` (compared as
integer ticks, `round(x/TICK)`), and its `sweep_ts` is at most 24h (resp.
72h) before this result's `sweep_ts`; otherwise `False`. A result whose
own `status` is `None` gets `None` for both flags. `run_engine` calls
`annotate_repeats` on the FULL per-call result list (every `sweep_idx` in
`[start_idx, end_idx]`) BEFORE applying `include_no_signal` filtering, so
the flags reflect exactly that one call's candidate set. These flags are
scoped to a SINGLE list: if a caller scans in chunks (multiple
`run_engine`/`evaluate_sweep_candidate` calls, e.g. for a long history),
each chunk's `run_engine` call only sees repeats within its own chunk --
to get flags that see across chunk boundaries, the caller must
concatenate the raw per-chunk results themselves and call
`annotate_repeats` once on the concatenated list (this module does not
do that automatically; it has no memory across calls). These flags are
REPORTING ONLY -- they never feed back into `status`/`stage`/routing.

MODULE 8b -- window gap diagnostics (`D3`): `EngineResult` gains
`window_max_gap_hours: float | None` and `window_spans_weekend: bool |
None`, populated ONLY once `simulate_entry` has actually run (i.e. the
pipeline reached step g -- reason `"ok"` from `compute_risk_reward`),
`None` before that. The timestamp sequence considered is: the activation
candle (`sweep_idx+1`, already read and validated in step d) followed by
the timestamp of every candle `simulate_entry` logged in its own
`result.candles` (each `WindowCandle.idx`) -- i.e. exactly the H1 rows
this pipeline already reads for `sweep_idx`, nothing extra.
`window_max_gap_hours` is the largest gap (in hours) between two
consecutive timestamps in that sequence; `window_spans_weekend` is
`window_max_gap_hours > 24`. If fewer than 2 timestamps are available
(e.g. no window candle was read at all), both stay `None`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import pandas as pd

from src.indicators.atr import atr as compute_atr
from src.market_structure.zones import create_zones, TICK
from src.signals.sweep import detect_sweep
from src.signals.m15_reaction import check_m15_reaction
from src.risk.risk_reward import compute_risk_reward
from src.execution.entry_simulation import simulate_entry


def _tick(x: float) -> int:
    return round(x / TICK)


def _validate_zone_width_atr(zone_width_atr) -> float:
    if isinstance(zone_width_atr, bool) or not isinstance(zone_width_atr, (int, float)):
        raise TypeError(f"zone_width_atr must be a number, got {type(zone_width_atr).__name__}")
    value = float(zone_width_atr)
    if not math.isfinite(value):
        raise ValueError(f"zone_width_atr must be finite, got {zone_width_atr!r}")
    if value <= 0:
        raise ValueError(f"zone_width_atr must be > 0, got {zone_width_atr!r}")
    return value


STATUS_NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
STATUS_REJECTED_M15_NO_REACTION = "REJECTED_M15_NO_REACTION"
STATUS_EXPIRED = "EXPIRED"
STATUS_REJECTED_RR_BELOW_THRESHOLD = "REJECTED_RR_BELOW_THRESHOLD"


@dataclass
class EngineResult:
    status: str | None
    stage: str
    entry_state: str | None
    sweep_idx: int
    sweep_ts: pd.Timestamp | None
    direction: str | None

    zone_low: float | None
    zone_center: float | None
    zone_high: float | None
    touch_count: int | None
    touch_idxs: list | None
    merged_rows: int | None

    atr_h1_14: float | None
    h1_range: float | None
    range_multiple: float | None
    pierce_depth: float | None
    sweep_extreme: float | None
    sweep_amplitude: float | None

    m15_candles: list | None
    m15_index_in_window: int | None
    activation_h1_open: pd.Timestamp | None

    entry: float | None
    stop: float | None
    tp1: float | None
    tp2: float | None
    rr_to_tp2: float | None
    rr_to_tp1: float | None
    fill_idx: int | None

    stop_breached_in_activation_hour: bool | None

    reason: str
    zone_candidates: list = field(default_factory=list)

    # module 8b
    zone_width_used: float | None = None
    zone_width_mode: str | None = None  # "absolute" | "atr" | None
    repeat_zone_within_24h: bool | None = None
    repeat_zone_within_72h: bool | None = None
    window_max_gap_hours: float | None = None
    window_spans_weekend: bool | None = None


def _empty_result(sweep_idx: int, stage: str, reason: str, sweep_ts=None) -> EngineResult:
    return EngineResult(
        status=None,
        stage=stage,
        entry_state=None,
        sweep_idx=sweep_idx,
        sweep_ts=sweep_ts,
        direction=None,
        zone_low=None,
        zone_center=None,
        zone_high=None,
        touch_count=None,
        touch_idxs=None,
        merged_rows=None,
        atr_h1_14=None,
        h1_range=None,
        range_multiple=None,
        pierce_depth=None,
        sweep_extreme=None,
        sweep_amplitude=None,
        m15_candles=None,
        m15_index_in_window=None,
        activation_h1_open=None,
        entry=None,
        stop=None,
        tp1=None,
        tp2=None,
        rr_to_tp2=None,
        rr_to_tp1=None,
        fill_idx=None,
        stop_breached_in_activation_hour=None,
        reason=reason,
    )


def _merge_zones(zones_df: pd.DataFrame) -> list[dict]:
    """Merge zone rows sharing the same (side, zone_low, zone_high). See
    module docstring ZONE MERGING."""
    groups: dict[tuple, list[dict]] = {}
    for _, row in zones_df.iterrows():
        key = (row["side"], row["zone_low"], row["zone_high"])
        groups.setdefault(key, []).append(row.to_dict())

    merged = []
    for (side, zone_low, zone_high), rows in groups.items():
        anchor_idx = min(r["anchor_idx"] for r in rows)
        first = rows[0]
        merged.append(
            {
                "side": side,
                "zone_low": zone_low,
                "zone_high": zone_high,
                "zone_center": first["zone_center"],
                "touch_count": first["touch_count"],
                "touch_idxs": first["touch_idxs"],
                "anchor_idx": anchor_idx,
                "merged_rows": len(rows),
            }
        )
    return merged


def evaluate_sweep_candidate(
    h1_df: pd.DataFrame,
    m15_df: pd.DataFrame,
    atr: pd.Series,
    sweep_idx: int,
    zone_width: float = 1.00,
    min_touches: int = 2,
    n: int = 3,
    range_prefilter: bool = True,
    zone_width_atr: float | None = None,
) -> EngineResult:
    """Run the full Dao Gam V1 pipeline for one candidate sweep candle.

    Pure function: takes all inputs explicitly, holds no state. See
    module docstring for the pipeline stages and ZONE MERGING/SELECTION
    rules.

    Parameters
    ----------
    h1_df : H1 OHLC DataFrame (with `timestamp`, `high`, `low`, `close`).
    m15_df : M15 OHLC DataFrame (with `timestamp`, `open`, `high`, `low`,
        `close`).
    atr : ATR Series aligned to `h1_df` positions (e.g.
        `src.indicators.atr.atr(h1_df, period=14)`), computed once by the
        caller -- not recomputed here.
    sweep_idx : positional (0-based) index of the candidate sweep candle.
    zone_width, min_touches, n : forwarded to `create_zones` /
        `find_swings` (via `compute_risk_reward`).
    range_prefilter : if `True` (default), a pure performance
        optimization run BEFORE `create_zones` is ever called: if the
        sweep candle's own `(high - low)` is less than
        `1.5 * atr.iloc[sweep_idx-1] - 2*TICK`, the candle cannot possibly
        satisfy `detect_sweep`'s own `range >= 1.5*atr` trap condition, so
        the pipeline short-circuits to `stage="no_trap"`, `status=None`,
        `reason` mentioning `"range_prefilter"`, without computing zones
        at all. The `-2*TICK` safety margin is MANDATORY: `detect_sweep`
        compares in tick-rounded integers (`>=`), so a candle whose raw
        float range is a hair below `1.5*atr` can still tick-round to a
        trap; subtracting `2*TICK` here guarantees this prefilter never
        rejects a candle that `detect_sweep` itself would still consider
        a trap. Set `False` to always call `create_zones` (e.g. for
        testing prefilter equivalence).
    zone_width_atr : optional (module 8b, `D1`). `None` (default): no
        change from prior behavior, `zone_width` is used as-is and
        `EngineResult.zone_width_mode` is `"absolute"`. Otherwise
        OVERRIDES `zone_width`: the effective width is
        `zone_width_atr * atr.iloc[sweep_idx-1]`, rounded to the nearest
        tick (floor 1 tick), and `zone_width_mode` is `"atr"`. See module
        docstring MODULE 8b section for full details and validation
        rules.

    Returns
    -------
    EngineResult. `status` is `None` unless the pipeline reached a stage
    that assigns a pipeline status.
    """
    if zone_width_atr is not None:
        _validate_zone_width_atr(zone_width_atr)

    if sweep_idx < 1 or sweep_idx >= len(h1_df) or pd.isna(atr.iloc[sweep_idx - 1]):
        return _empty_result(sweep_idx, "atr_unavailable", "ATR not available for sweep_idx-1")

    sweep_ts = pd.to_datetime(h1_df["timestamp"].iloc[sweep_idx], utc=True)

    if range_prefilter:
        sweep_high = float(h1_df["high"].iloc[sweep_idx])
        sweep_low = float(h1_df["low"].iloc[sweep_idx])
        atr_at_idx_minus_1 = float(atr.iloc[sweep_idx - 1])
        if (sweep_high - sweep_low) < 1.5 * atr_at_idx_minus_1 - 2 * TICK:
            return _empty_result(
                sweep_idx,
                "no_trap",
                "range_prefilter: sweep candle range below 1.5*atr-2*TICK, skipped create_zones",
                sweep_ts=sweep_ts,
            )

    if zone_width_atr is None:
        effective_width = zone_width
        zone_width_mode = "absolute"
    else:
        atr_prev = float(atr.iloc[sweep_idx - 1])
        raw_width = _validate_zone_width_atr(zone_width_atr) * atr_prev
        ticks = max(round(raw_width / TICK), 1)
        effective_width = round(ticks * TICK, 10)
        zone_width_mode = "atr"

    zones_df = create_zones(h1_df, as_of=sweep_idx - 1, n=n, width=effective_width, min_touches=min_touches)
    if zones_df.empty:
        result = _empty_result(sweep_idx, "no_trap", "No confirmed zone as of sweep_idx-1", sweep_ts=sweep_ts)
        result.zone_width_used = effective_width
        result.zone_width_mode = zone_width_mode
        return result

    merged_zones = _merge_zones(zones_df)

    zone_candidates = []
    trapped = []
    for mz in merged_zones:
        zone_arg = {
            "side": mz["side"],
            "zone_low": mz["zone_low"],
            "zone_center": mz["zone_center"],
            "zone_high": mz["zone_high"],
        }
        sweep_result = detect_sweep(h1_df, atr, sweep_idx, zone_arg)
        zone_candidates.append({"zone": mz, "sweep_result": sweep_result})
        if sweep_result.is_trap:
            trapped.append((mz, sweep_result))

    if not trapped:
        result = _empty_result(
            sweep_idx, "no_trap", "No candidate zone produced a confirmed trap at sweep_idx", sweep_ts=sweep_ts
        )
        result.zone_candidates = zone_candidates
        result.zone_width_used = effective_width
        result.zone_width_mode = zone_width_mode
        return result

    sweep_close = float(h1_df["close"].iloc[sweep_idx])

    def selection_key(item):
        mz, sr = item
        return (-mz["touch_count"], abs(sweep_close - mz["zone_center"]), -mz["anchor_idx"])

    trapped.sort(key=selection_key)
    winning_zone, sweep_result = trapped[0]

    direction = sweep_result.direction
    zone_center = winning_zone["zone_center"]
    zone_low = winning_zone["zone_low"]
    zone_high = winning_zone["zone_high"]

    # Step d: activation bar must exist with an exact +1h gap.
    activation_idx = sweep_idx + 1
    if activation_idx >= len(h1_df):
        result = _empty_result(sweep_idx, "activation_bar_missing", "No H1 row at sweep_idx+1", sweep_ts=sweep_ts)
        result.zone_candidates = zone_candidates
        result.direction = direction
        result.zone_low, result.zone_center, result.zone_high = zone_low, zone_center, zone_high
        result.touch_count, result.touch_idxs, result.merged_rows = (
            winning_zone["touch_count"],
            winning_zone["touch_idxs"],
            winning_zone["merged_rows"],
        )
        result.atr_h1_14 = sweep_result.atr_h1_14
        result.h1_range = sweep_result.h1_range
        result.range_multiple = sweep_result.range_multiple
        result.pierce_depth = sweep_result.pierce_depth
        result.sweep_extreme = sweep_result.sweep_extreme
        result.zone_width_used = effective_width
        result.zone_width_mode = zone_width_mode
        return result

    activation_ts = pd.to_datetime(h1_df["timestamp"].iloc[activation_idx], utc=True)
    if activation_ts != sweep_ts + pd.Timedelta(hours=1):
        result = _empty_result(
            sweep_idx, "activation_bar_missing", "H1 row at sweep_idx+1 is not exactly 1h after sweep_idx", sweep_ts=sweep_ts
        )
        result.zone_candidates = zone_candidates
        result.direction = direction
        result.zone_low, result.zone_center, result.zone_high = zone_low, zone_center, zone_high
        result.touch_count, result.touch_idxs, result.merged_rows = (
            winning_zone["touch_count"],
            winning_zone["touch_idxs"],
            winning_zone["merged_rows"],
        )
        result.atr_h1_14 = sweep_result.atr_h1_14
        result.h1_range = sweep_result.h1_range
        result.range_multiple = sweep_result.range_multiple
        result.pierce_depth = sweep_result.pierce_depth
        result.sweep_extreme = sweep_result.sweep_extreme
        result.zone_width_used = effective_width
        result.zone_width_mode = zone_width_mode
        return result

    base_reason = (
        f"zone=[{zone_low},{zone_center},{zone_high}] touch_count={winning_zone['touch_count']} "
        f"atr_h1_14={sweep_result.atr_h1_14} h1_range={sweep_result.h1_range} "
        f"range_multiple={sweep_result.range_multiple} pierce_depth={sweep_result.pierce_depth} "
        f"sweep_extreme={sweep_result.sweep_extreme}"
    )

    def _base_result(stage: str, status: str | None, reason_suffix: str) -> EngineResult:
        r = _empty_result(sweep_idx, stage, f"{base_reason} {reason_suffix}", sweep_ts=sweep_ts)
        r.status = status
        r.direction = direction
        r.zone_low, r.zone_center, r.zone_high = zone_low, zone_center, zone_high
        r.touch_count = winning_zone["touch_count"]
        r.touch_idxs = winning_zone["touch_idxs"]
        r.merged_rows = winning_zone["merged_rows"]
        r.atr_h1_14 = sweep_result.atr_h1_14
        r.h1_range = sweep_result.h1_range
        r.range_multiple = sweep_result.range_multiple
        r.pierce_depth = sweep_result.pierce_depth
        r.sweep_extreme = sweep_result.sweep_extreme
        r.sweep_amplitude = None
        r.zone_candidates = zone_candidates
        r.zone_width_used = effective_width
        r.zone_width_mode = zone_width_mode
        return r

    # Step e: M15 reaction.
    m15_result = check_m15_reaction(m15_df, sweep_ts, direction, zone_center)

    if m15_result.outcome == "no_reaction":
        r = _base_result("m15_no_reaction", STATUS_REJECTED_M15_NO_REACTION, "m15_outcome=no_reaction")
        r.m15_candles = m15_result.candles
        return r

    if m15_result.outcome == "window_incomplete":
        r = _base_result("m15_window_incomplete", None, "m15_outcome=window_incomplete")
        r.m15_candles = m15_result.candles
        return r

    # m15_result.outcome == "fired"
    rr_result = compute_risk_reward(
        h1_df,
        sweep_idx=sweep_idx,
        direction=direction,
        zone_center=zone_center,
        sweep_extreme=sweep_result.sweep_extreme,
        atr_h1_14=sweep_result.atr_h1_14,
        n=n,
    )

    def _rr_reason(extra: str) -> str:
        m15_desc = (
            f"m15_fired_index={m15_result.fired_index} "
            f"m15_candles={[(c.timestamp, c.close, c.body_ratio, c.close_position_in_range) for c in m15_result.candles]}"
        )
        return f"{base_reason} sweep_amplitude={rr_result.sweep_amplitude} {m15_desc} {extra}"

    # Diagnostic only (does not change status/stage/routing): whether any
    # of the M15 candles logged by check_m15_reaction (from the first
    # candle up to and including the one that fired) already touched the
    # stop-loss level, compared in integer ticks. Only meaningful once
    # M15 has fired (we need `rr_result.stop`, which is always populated
    # regardless of rr_result.reason).
    stop_t = _tick(rr_result.stop)
    if direction == "buy":
        stop_breached_in_activation_hour = any(_tick(c.low) <= stop_t for c in m15_result.candles)
    else:
        stop_breached_in_activation_hour = any(_tick(c.high) >= stop_t for c in m15_result.candles)

    if rr_result.reason == "tp1_unavailable":
        r = _base_result("tp1_unavailable", None, _rr_reason("rr_reason=tp1_unavailable"))
        r.m15_candles = m15_result.candles
        r.m15_index_in_window = m15_result.fired_index
        r.activation_h1_open = m15_result.activation_h1_open
        r.sweep_amplitude = rr_result.sweep_amplitude
        r.entry = rr_result.entry
        r.stop = rr_result.stop
        r.stop_breached_in_activation_hour = stop_breached_in_activation_hour
        return r

    if rr_result.reason == "rr_below_threshold":
        r = _base_result(
            "rr_below_threshold", STATUS_REJECTED_RR_BELOW_THRESHOLD, _rr_reason(f"rr_to_tp2={rr_result.rr_to_tp2}")
        )
        r.m15_candles = m15_result.candles
        r.m15_index_in_window = m15_result.fired_index
        r.activation_h1_open = m15_result.activation_h1_open
        r.sweep_amplitude = rr_result.sweep_amplitude
        r.entry = rr_result.entry
        r.stop = rr_result.stop
        r.tp1 = rr_result.tp1
        r.tp2 = rr_result.tp2
        r.rr_to_tp2 = rr_result.rr_to_tp2
        r.rr_to_tp1 = rr_result.rr_to_tp1
        r.stop_breached_in_activation_hour = stop_breached_in_activation_hour
        return r

    # rr_result.reason == "ok"
    entry_result = simulate_entry(
        h1_df, activation_idx=sweep_idx + 1, direction=direction, entry=rr_result.entry, stop=rr_result.stop
    )

    # D3 (module 8b): max gap between consecutive timestamps in exactly
    # the H1 rows this pipeline read for the entry window -- the
    # activation candle plus every candle simulate_entry logged (its own
    # `candles[i].idx`), nothing beyond that.
    window_ts_seq = [activation_ts] + [
        pd.to_datetime(h1_df["timestamp"].iloc[c.idx], utc=True) for c in entry_result.candles
    ]
    if len(window_ts_seq) >= 2:
        window_gaps_hours = [
            (b - a).total_seconds() / 3600.0 for a, b in zip(window_ts_seq, window_ts_seq[1:])
        ]
        window_max_gap_hours = max(window_gaps_hours)
        window_spans_weekend = window_max_gap_hours > 24
    else:
        window_max_gap_hours = None
        window_spans_weekend = None

    entry_reason = _rr_reason(f"rr_to_tp2={rr_result.rr_to_tp2} entry_outcome={entry_result.outcome}")

    if entry_result.outcome == "expired":
        r = _base_result("expired", STATUS_EXPIRED, entry_reason)
    elif entry_result.outcome == "filled":
        r = _base_result("filled", STATUS_NEEDS_MANUAL_REVIEW, entry_reason)
        r.entry_state = "filled"
        r.fill_idx = entry_result.fill_idx
    else:  # window_incomplete
        r = _base_result("pending", STATUS_NEEDS_MANUAL_REVIEW, entry_reason)
        r.entry_state = "pending"

    r.m15_candles = m15_result.candles
    r.m15_index_in_window = m15_result.fired_index
    r.activation_h1_open = m15_result.activation_h1_open
    r.sweep_amplitude = rr_result.sweep_amplitude
    r.entry = rr_result.entry
    r.stop = rr_result.stop
    r.tp1 = rr_result.tp1
    r.tp2 = rr_result.tp2
    r.rr_to_tp2 = rr_result.rr_to_tp2
    r.rr_to_tp1 = rr_result.rr_to_tp1
    r.stop_breached_in_activation_hour = stop_breached_in_activation_hour
    r.window_max_gap_hours = window_max_gap_hours
    r.window_spans_weekend = window_spans_weekend
    return r


def annotate_repeats(results: list[EngineResult]) -> list[EngineResult]:
    """Set `repeat_zone_within_24h`/`repeat_zone_within_72h` (module 8b,
    `D2`) on a COPY of `results` -- never mutates its argument.

    For each result with a non-`None` `status`, each flag is `True` if
    some OTHER result earlier in `results` (by `sweep_ts`, strictly
    smaller) also has a non-`None` `status`, the same `direction`, the
    same `zone_center` (compared as integer ticks), and its `sweep_ts` is
    at most 24h (resp. 72h) before this result's `sweep_ts`. A result
    whose own `status` is `None` gets `None` for both flags. The
    comparison only ever looks backward in `sweep_ts` order -- a later
    result never affects an earlier one's flags.

    These flags are scoped to exactly the list passed in. See module
    docstring MODULE 8b section for how to combine multiple chunked
    scans. Purely a reporting aid -- never used to gate `status`/`stage`.
    """
    output = [replace(r) for r in results]

    candidates = [
        (i, r) for i, r in enumerate(results) if r.status is not None and r.sweep_ts is not None
    ]
    candidates.sort(key=lambda item: item[1].sweep_ts)

    history: dict[tuple, list] = {}
    for i, r in candidates:
        zone_center_tick = _tick(r.zone_center) if r.zone_center is not None else None
        key = (r.direction, zone_center_tick)
        prior_ts_list = history.setdefault(key, [])

        repeat_24h = False
        repeat_72h = False
        for prior_ts in prior_ts_list:
            if prior_ts >= r.sweep_ts:
                continue
            delta_hours = (r.sweep_ts - prior_ts).total_seconds() / 3600.0
            if delta_hours <= 24:
                repeat_24h = True
            if delta_hours <= 72:
                repeat_72h = True

        output[i].repeat_zone_within_24h = repeat_24h
        output[i].repeat_zone_within_72h = repeat_72h
        prior_ts_list.append(r.sweep_ts)

    return output


def run_engine(
    h1_df: pd.DataFrame,
    m15_df: pd.DataFrame,
    start_idx: int | None = None,
    end_idx: int | None = None,
    include_no_signal: bool = False,
    zone_width: float = 1.00,
    min_touches: int = 2,
    n: int = 3,
    atr_period: int = 14,
    range_prefilter: bool = True,
    zone_width_atr: float | None = None,
) -> list[EngineResult]:
    """Scan `h1_df` for sweep candidates and evaluate each with
    `evaluate_sweep_candidate`. ATR is computed once (via
    `src.indicators.atr.atr`) and reused for every candidate.

    Parameters
    ----------
    start_idx, end_idx : inclusive positional bounds on `sweep_idx` to
        scan (default: the full range `[0, len(h1_df)-1]`).
    include_no_signal : if `False` (default), only results with a
        non-`None` `status` are returned. If `True`, every evaluated
        `EngineResult` is returned regardless of `status`.
    zone_width, min_touches, n, atr_period : forwarded to the pipeline.
    range_prefilter : forwarded to `evaluate_sweep_candidate` (see its
        docstring) -- a performance optimization only, does not change
        results for any candidate that reaches a non-`None` status.
    zone_width_atr : forwarded to `evaluate_sweep_candidate` (module 8b,
        `D1`). `None` (default) reproduces prior behavior exactly.

    Returns
    -------
    list[EngineResult]. `annotate_repeats` (module 8b, `D2`) is called on
    the FULL per-call result list (every `sweep_idx` in `[start_idx,
    end_idx]`) BEFORE `include_no_signal` filtering is applied, so the
    repeat flags reflect exactly this one call's candidate set. No
    cooldown or overlap suppression is applied (out of scope; see module
    docstring).
    """
    atr = compute_atr(h1_df, period=atr_period)

    lo = 0 if start_idx is None else start_idx
    hi = len(h1_df) - 1 if end_idx is None else end_idx

    all_results = []
    for sweep_idx in range(lo, hi + 1):
        result = evaluate_sweep_candidate(
            h1_df,
            m15_df,
            atr,
            sweep_idx,
            zone_width=zone_width,
            min_touches=min_touches,
            n=n,
            range_prefilter=range_prefilter,
            zone_width_atr=zone_width_atr,
        )
        all_results.append(result)

    annotated = annotate_repeats(all_results)

    if include_no_signal:
        return annotated
    return [r for r in annotated if r.status is not None]
