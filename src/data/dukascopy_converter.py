"""Convert a raw Dukascopy XAUUSD M15 CSV export into DATA_SCHEMA-conformant
H1/M15 CSV files (module 9a).

Input format (Dukascopy "Bid" M15 export): a CSV with header exactly
`Etc/UTC,Open,High,Low,Close,Volume`, one row per M15 candle, timestamps
of the form `YYYY-MM-DDTHH:MM:SS+00:00` (UTC only -- any other offset is
a hard error). This module does not know about zones, sweeps, ATR, or
signals -- it only reshapes raw OHLCV rows into `docs/DATA_SCHEMA.md`
Section 1's `timestamp,symbol,timeframe,open,high,low,close,volume`
column set for H1 and M15, plus an aggregate `conversion_report.json`.

This module never imports from `tests/` (matches every other production
module in this repo) and never calls into `src.engine`/`src.signals`/etc.
-- it is a pure data-preparation step, run before the engine, not part
of it.

VALUES: prices and volume are parsed with `decimal.Decimal` from the raw
CSV text -- never through `float` -- to avoid binary floating-point noise
before the deliberate `ROUND_HALF_UP` rounding to the instrument's tick
size (`docs/DATA_SCHEMA.md` Section 3, `tick_size = 0.01` for XAUUSD).

ERROR HANDLING (two tiers):
  - HARD ERRORS (`ConversionError`, raised immediately, no output written):
    a wrong header line; a timestamp that doesn't parse as
    `YYYY-MM-DDTHH:MM:SS<offset>`; a UTC offset other than `+00:00`; a
    timestamp not aligned to `:00/:15/:30/:45`; a duplicate timestamp; a
    timestamp that is not strictly increasing relative to the previous
    row. These are treated as hard because they mean the input file
    itself cannot be trusted to represent a single, ordered M15 series
    -- silently coping (e.g. sorting) would hide a data problem instead
    of surfacing it.
  - SOFT ERRORS (row excluded from output, never mutated, always logged
    with its 1-based source line number and reason): an empty or
    non-numeric OHLCV cell; a non-positive price; a negative volume; OHLC
    internally inconsistent (`high < max(open, close, low)` or
    `low > min(open, close, high)`) after rounding. A flat candle
    (`high == low`) and a `volume == 0` candle are both valid -- they are
    only counted/reported, never excluded.

NO IMPLICIT SORTING: rows are processed in the exact order they appear in
the file. If that order is not strictly increasing, this is a hard error
(see above), never silently corrected.

--exclude-file: an optional CSV with a single ISO-timestamp column
(same `YYYY-MM-DDTHH:MM:SS+00:00` format, validated the same way) naming
M15 candles to treat as missing (e.g. a known-partial candle that will be
backfilled later). Matching rows are removed from both the M15 output and
any H1 hour they would have completed; they are not treated as a
different kind of error, just a caller-directed exclusion.

H1 AGGREGATION: an H1 hour is only emitted if all 4 of its M15 quarters
(`:00`, `:15`, `:30`, `:45`) survive the soft-error and exclude-file
filtering. `open` = the `:00` candle's open, `close` = the `:45` candle's
close, `high`/`low` = the max/min across the 4, `volume` = their sum
(computed in `Decimal`, never `float`). An incomplete hour is dropped
from H1 output (its surviving M15 candles are still written to `m15.csv`)
and listed in the report's `partial_hours`. No missing candle is ever
synthesized/filled.

OUTPUT: `h1.csv` / `m15.csv` with columns `timestamp,symbol,timeframe,
open,high,low,close,volume` (`docs/DATA_SCHEMA.md` Section 1), timestamp
formatted `YYYY-MM-DDTHH:MM:SSZ`, `symbol` fixed to the CLI's `--symbol`
value (`XAUUSD` by default), prices as fixed 2-decimal strings, and rows
in strictly increasing timestamp order (guaranteed by construction, since
the source order was already validated strictly increasing and no
re-sorting ever happens). Deterministic: the same input (and the same
`--exclude-file`, if any) always produces byte-identical output.

ASSUMPTIONS (not specified in the docs, decided here):
  - `conversion_report.json`'s `gap_stats` / `weekend_gap_check` /
    `hourly_profile` / `decode_sanity` sections are computed over the
    final M15 output (post soft-error and exclude-file filtering), since
    that is the finest-grained series this module produces.
  - Rounding statistics (`rounding.count_rounded` / `max_deviation`) are
    counted per OHLC price field (not per row), across every row whose
    price fields parsed successfully as `Decimal`, regardless of whether
    that row is later excluded for a different reason (invalid OHLC,
    non-positive price, negative volume) -- rounding itself is a
    unconditional step applied before those checks run.
  - The `--exclude-file`'s "did not match any candle" count is computed
    against the set of *valid* M15 candidates (post soft-error
    filtering, pre exclude-file) -- i.e. "no candle" means "no surviving
    candle", not merely "no raw input row", since a soft-excluded row was
    never a candle in this module's output sense either.
  - `decode_sanity`'s percentiles use linear-interpolation ("nearest
    two data points") on the sorted sample -- a specific but reasonable
    choice, not something `docs/DATA_SCHEMA.md` specifies.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

EXPECTED_HEADER = ["Etc/UTC", "Open", "High", "Low", "Close", "Volume"]
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})([+-]\d{2}:\d{2})$")
VALID_MINUTES = (0, 15, 30, 45)
TICK = Decimal("0.01")
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class ConversionError(ValueError):
    """Hard error: the input cannot be trusted; no output is written."""


@dataclass
class Candle:
    line_no: int
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass
class ExcludedRow:
    line_no: int
    timestamp: str
    reason: str


@dataclass
class ParseResult:
    valid: list = field(default_factory=list)  # list[Candle], in file order
    excluded: list = field(default_factory=list)  # list[ExcludedRow]
    rounding_count: int = 0
    rounding_max_deviation: Decimal = Decimal("0")


def _parse_timestamp(raw: str, line_no: int) -> datetime:
    m = TS_RE.match(raw.strip())
    if not m:
        raise ConversionError(
            f"line {line_no}: timestamp {raw!r} could not be parsed "
            f"(expected YYYY-MM-DDTHH:MM:SS+00:00)"
        )
    dt_part, offset = m.groups()
    if offset != "+00:00":
        raise ConversionError(f"line {line_no}: timestamp {raw!r} has non-zero UTC offset {offset!r}")
    try:
        dt = datetime.strptime(dt_part, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ConversionError(f"line {line_no}: timestamp {raw!r} is not a valid date/time ({e})") from e
    if dt.minute not in VALID_MINUTES or dt.second != 0:
        raise ConversionError(
            f"line {line_no}: timestamp {raw!r} is not aligned to :00/:15/:30/:45"
        )
    return dt


def _validate_header(header: list[str], path: Path) -> None:
    if header != EXPECTED_HEADER:
        raise ConversionError(
            f"{path}: header must be exactly {','.join(EXPECTED_HEADER)!r}, got {','.join(header)!r}"
        )


def _round_price(raw: Decimal) -> Decimal:
    return raw.quantize(TICK, rounding=ROUND_HALF_UP)


def parse_m15_csv(path: Path) -> ParseResult:
    """Parse and validate a raw Dukascopy M15 CSV.

    Raises `ConversionError` (hard) on a bad header, an unparseable or
    misaligned timestamp, a duplicate, or a non-strictly-increasing
    timestamp -- these stop processing entirely, before any row is
    excluded or written anywhere. Everything else (empty/non-numeric
    cells, non-positive price, negative volume, invalid OHLC after
    rounding) is a soft error: the row is excluded and logged, parsing
    continues.
    """
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise ConversionError(f"{path}: file is empty (no header row)") from None
        _validate_header(header, path)

        rows = list(reader)

    # Pass 1: parse + validate every timestamp (hard errors), in file
    # order, with no sorting. Track (line_no, ts, raw_fields).
    parsed_ts: list[tuple[int, datetime, list[str]]] = []
    line_no = 1  # header is line 1
    prev_ts: datetime | None = None
    prev_line: int | None = None
    for raw_fields in rows:
        line_no += 1
        if not raw_fields:
            continue  # skip fully blank lines (no data to validate)
        ts_raw = raw_fields[0] if raw_fields else ""
        ts = _parse_timestamp(ts_raw, line_no)
        if prev_ts is not None:
            if ts == prev_ts:
                raise ConversionError(
                    f"line {line_no}: duplicate timestamp {ts_raw!r} (also at line {prev_line})"
                )
            if ts < prev_ts:
                raise ConversionError(
                    f"line {line_no}: timestamp {ts_raw!r} is out of order "
                    f"(previous row at line {prev_line} was later)"
                )
        prev_ts, prev_line = ts, line_no
        parsed_ts.append((line_no, ts, raw_fields))

    # Pass 2: soft validation of the numeric fields.
    result = ParseResult()
    for line_no, ts, raw_fields in parsed_ts:
        if len(raw_fields) != 6:
            result.excluded.append(ExcludedRow(line_no, raw_fields[0], "malformed_row_field_count"))
            continue

        _, o_raw, h_raw, l_raw, c_raw, v_raw = raw_fields
        try:
            o = Decimal(o_raw.strip())
            h = Decimal(h_raw.strip())
            l = Decimal(l_raw.strip())
            c = Decimal(c_raw.strip())
            v = Decimal(v_raw.strip())
        except (InvalidOperation, ValueError):
            result.excluded.append(ExcludedRow(line_no, raw_fields[0], "non_numeric_or_empty"))
            continue

        o_r, h_r, l_r, c_r = _round_price(o), _round_price(h), _round_price(l), _round_price(c)
        for raw_val, rounded_val in ((o, o_r), (h, h_r), (l, l_r), (c, c_r)):
            deviation = abs(raw_val - rounded_val)
            if deviation != 0:
                result.rounding_count += 1
                if deviation > result.rounding_max_deviation:
                    result.rounding_max_deviation = deviation

        if o_r <= 0 or h_r <= 0 or l_r <= 0 or c_r <= 0:
            result.excluded.append(ExcludedRow(line_no, raw_fields[0], "non_positive_price"))
            continue
        if v < 0:
            result.excluded.append(ExcludedRow(line_no, raw_fields[0], "negative_volume"))
            continue
        if h_r < max(o_r, c_r, l_r) or l_r > min(o_r, c_r, h_r):
            result.excluded.append(ExcludedRow(line_no, raw_fields[0], "invalid_ohlc"))
            continue

        result.valid.append(Candle(line_no=line_no, ts=ts, open=o_r, high=h_r, low=l_r, close=c_r, volume=v))

    return result


def parse_exclude_file(path: Path) -> set[datetime]:
    """Parse a single-column ISO-timestamp exclude file. Each timestamp is
    validated with the same format/alignment rules as the main input
    (hard errors on malformed rows); duplicate timestamps within this
    file are harmless and silently deduplicated."""
    excluded: set[datetime] = set()
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for i, raw_fields in enumerate(reader, start=1):
            if not raw_fields or not raw_fields[0].strip():
                continue
            first = raw_fields[0].strip()
            if i == 1 and first.lower() in ("timestamp", "etc/utc"):
                continue  # optional header row
            excluded.add(_parse_timestamp(first, i))
    return excluded


def _percentile(sorted_values: list[Decimal], pct: float) -> Decimal:
    """Linear-interpolation percentile on an already-sorted list."""
    if not sorted_values:
        return Decimal("0")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = Decimal(str(pct)) * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_price(d: Decimal) -> str:
    return f"{d.quantize(TICK, rounding=ROUND_HALF_UP):.2f}"


def _fmt_volume(d: Decimal) -> str:
    if d == d.to_integral_value():
        return str(int(d))
    return str(d.normalize())


def _decimal_str(d: Decimal) -> str:
    return str(d.normalize()) if d == d.to_integral_value() else str(d)


def build_h1(m15_valid: list[Candle]) -> tuple[list[Candle], list[dict]]:
    """Aggregate M15 candles into H1 candles. Returns (h1_candles,
    partial_hours) -- see module docstring H1 AGGREGATION."""
    by_hour: "defaultdict[datetime, dict[int, Candle]]" = defaultdict(dict)
    for c in m15_valid:
        hour_key = c.ts.replace(minute=0)
        by_hour[hour_key][c.ts.minute] = c

    h1_candles: list[Candle] = []
    partial_hours: list[dict] = []
    for hour_key in sorted(by_hour.keys()):
        quarters = by_hour[hour_key]
        if set(quarters.keys()) == set(VALID_MINUTES):
            q0, q15, q30, q45 = quarters[0], quarters[15], quarters[30], quarters[45]
            h1_candles.append(
                Candle(
                    line_no=q0.line_no,
                    ts=hour_key,
                    open=q0.open,
                    high=max(q0.high, q15.high, q30.high, q45.high),
                    low=min(q0.low, q15.low, q30.low, q45.low),
                    close=q45.close,
                    volume=q0.volume + q15.volume + q30.volume + q45.volume,
                )
            )
        else:
            partial_hours.append(
                {
                    "hour": _fmt_ts(hour_key),
                    "present_minutes": sorted(quarters.keys()),
                    "missing_minutes": sorted(set(VALID_MINUTES) - set(quarters.keys())),
                }
            )
    return h1_candles, partial_hours


def _write_csv(path: Path, candles: list[Candle], timeframe: str, symbol: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume"])
        for c in candles:
            writer.writerow(
                [
                    _fmt_ts(c.ts),
                    symbol,
                    timeframe,
                    _fmt_price(c.open),
                    _fmt_price(c.high),
                    _fmt_price(c.low),
                    _fmt_price(c.close),
                    _fmt_volume(c.volume),
                ]
            )


def _classify_gap(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600.0
    if hours <= 1:
        return "<=1h"
    if hours <= 24:
        return "1-24h"
    return ">24h"


def _build_gap_stats(m15_valid: list[Candle]) -> dict:
    buckets = {"<=1h": 0, "1-24h": 0, ">24h": 0}
    gaps: list[dict] = []
    for prev, cur in zip(m15_valid, m15_valid[1:]):
        delta = cur.ts - prev.ts
        bucket = _classify_gap(delta)
        buckets[bucket] += 1
        gaps.append(
            {
                "from": _fmt_ts(prev.ts),
                "to": _fmt_ts(cur.ts),
                "gap_hours": float(delta.total_seconds() / 3600.0),
            }
        )
    gaps.sort(key=lambda g: g["gap_hours"], reverse=True)
    return {"buckets": buckets, "longest_30": gaps[:30]}


def _build_weekend_gap_check(m15_valid: list[Candle]) -> dict:
    events: list[dict] = []
    before_by_month: "defaultdict[str, Counter]" = defaultdict(Counter)
    after_by_month: "defaultdict[str, Counter]" = defaultdict(Counter)
    for prev, cur in zip(m15_valid, m15_valid[1:]):
        delta = cur.ts - prev.ts
        if delta.total_seconds() / 3600.0 <= 24:
            continue
        before = {
            "timestamp": _fmt_ts(prev.ts),
            "weekday": WEEKDAY_NAMES[prev.ts.weekday()],
            "time_utc": prev.ts.strftime("%H:%M"),
            "date": prev.ts.strftime("%Y-%m-%d"),
        }
        after = {
            "timestamp": _fmt_ts(cur.ts),
            "weekday": WEEKDAY_NAMES[cur.ts.weekday()],
            "time_utc": cur.ts.strftime("%H:%M"),
            "date": cur.ts.strftime("%Y-%m-%d"),
        }
        events.append({"before": before, "after": after, "gap_hours": float(delta.total_seconds() / 3600.0)})
        month_key = prev.ts.strftime("%Y-%m")
        before_by_month[month_key][prev.ts.strftime("%H:%M")] += 1
        after_by_month[cur.ts.strftime("%Y-%m")][cur.ts.strftime("%H:%M")] += 1

    monthly = {}
    months = sorted(set(before_by_month.keys()) | set(after_by_month.keys()))
    for month in months:
        monthly[month] = {
            "most_common_before_time_utc": before_by_month[month].most_common(1)[0][0]
            if before_by_month[month]
            else None,
            "most_common_after_time_utc": after_by_month[month].most_common(1)[0][0]
            if after_by_month[month]
            else None,
        }

    return {"events": events, "monthly_most_common_times": monthly}


def _build_hourly_profile(m15_valid: list[Candle]) -> dict:
    counts = [0] * 24
    flats = [0] * 24
    vol_sums = [Decimal("0")] * 24
    for c in m15_valid:
        h = c.ts.hour
        counts[h] += 1
        if c.high == c.low:
            flats[h] += 1
        vol_sums[h] += c.volume

    profile = {}
    for h in range(24):
        avg_vol = float(vol_sums[h] / counts[h]) if counts[h] else 0.0
        profile[f"{h:02d}"] = {"count": counts[h], "flat_count": flats[h], "avg_volume": round(avg_vol, 4)}
    return profile


def _build_decode_sanity(m15_valid: list[Candle]) -> dict:
    ranges = sorted(
        ({"timestamp": _fmt_ts(c.ts), "range": _decimal_str(c.high - c.low)} for c in m15_valid),
        key=lambda r: Decimal(r["range"]),
        reverse=True,
    )[:20]

    jumps: list[dict] = []
    jump_values: list[Decimal] = []
    for prev, cur in zip(m15_valid, m15_valid[1:]):
        if cur.ts - prev.ts != timedelta(minutes=15):
            continue
        diff = abs(cur.open - prev.close)
        jump_values.append(diff)
        jumps.append(
            {
                "prev_timestamp": _fmt_ts(prev.ts),
                "cur_timestamp": _fmt_ts(cur.ts),
                "abs_open_minus_prev_close": _decimal_str(diff),
            }
        )
    jumps.sort(key=lambda j: Decimal(j["abs_open_minus_prev_close"]), reverse=True)
    jump_values.sort()

    stats = {
        "median": _decimal_str(_percentile(jump_values, 0.50)),
        "p95": _decimal_str(_percentile(jump_values, 0.95)),
        "p99": _decimal_str(_percentile(jump_values, 0.99)),
        "p999": _decimal_str(_percentile(jump_values, 0.999)),
    }
    return {"largest_ranges": ranges, "largest_open_close_jumps": jumps[:20], "jump_stats": stats}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def convert(
    input_path: Path,
    outdir: Path,
    exclude_path: Path | None = None,
    symbol: str = "XAUUSD",
) -> dict:
    """Run the full conversion. Writes `h1.csv`, `m15.csv`, and
    `conversion_report.json` into `outdir` (created if needed). Returns
    the report dict (identical to what is written to
    `conversion_report.json`). Raises `ConversionError` (and writes
    nothing) on any hard error. `input_path` is only ever read, never
    modified."""
    input_path = Path(input_path)
    outdir = Path(outdir)
    input_sha256 = sha256_of(input_path)

    parsed = parse_m15_csv(input_path)

    exclude_ts: set[datetime] = set()
    if exclude_path is not None:
        exclude_ts = parse_exclude_file(Path(exclude_path))

    excluded_by_exclude_file = 0
    m15_after_exclude: list[Candle] = []
    for c in parsed.valid:
        if c.ts in exclude_ts:
            excluded_by_exclude_file += 1
        else:
            m15_after_exclude.append(c)

    matched_exclude_ts = {c.ts for c in parsed.valid if c.ts in exclude_ts}
    unmatched_exclude_lines = len(exclude_ts - matched_exclude_ts)

    h1_candles, partial_hours = build_h1(m15_after_exclude)

    outdir.mkdir(parents=True, exist_ok=True)
    _write_csv(outdir / "h1.csv", h1_candles, "H1", symbol)
    _write_csv(outdir / "m15.csv", m15_after_exclude, "M15", symbol)

    reason_counts: "Counter[str]" = Counter(row.reason for row in parsed.excluded)
    flat_count = sum(1 for c in m15_after_exclude if c.high == c.low)
    zero_volume_count = sum(1 for c in m15_after_exclude if c.volume == 0)

    m15_by_month: "Counter[str]" = Counter(c.ts.strftime("%Y-%m") for c in m15_after_exclude)
    h1_by_month: "Counter[str]" = Counter(c.ts.strftime("%Y-%m") for c in h1_candles)

    report = {
        "input_file": {"path": str(input_path), "sha256": input_sha256},
        "rows_read": len(parsed.valid) + len(parsed.excluded),
        "rows_excluded": {
            "total": len(parsed.excluded),
            "by_reason": dict(sorted(reason_counts.items())),
            "rows": [
                {"line": r.line_no, "timestamp": r.timestamp, "reason": r.reason}
                for r in sorted(parsed.excluded, key=lambda r: r.line_no)
            ],
        },
        "exclude_file": {
            "used": exclude_path is not None,
            "path": str(exclude_path) if exclude_path is not None else None,
            "excluded_candles": excluded_by_exclude_file,
            "unmatched_lines": unmatched_exclude_lines,
        },
        "date_range": {
            "start": _fmt_ts(m15_after_exclude[0].ts) if m15_after_exclude else None,
            "end": _fmt_ts(m15_after_exclude[-1].ts) if m15_after_exclude else None,
        },
        "counts": {"m15": len(m15_after_exclude), "h1": len(h1_candles)},
        "candles_by_month": {
            "m15": dict(sorted(m15_by_month.items())),
            "h1": dict(sorted(h1_by_month.items())),
        },
        "hours": {"complete": len(h1_candles), "incomplete": len(partial_hours)},
        "partial_hours": partial_hours,
        "rounding": {
            "count_rounded": parsed.rounding_count,
            "max_deviation": _decimal_str(parsed.rounding_max_deviation),
        },
        "flat_candles": flat_count,
        "zero_volume_candles": zero_volume_count,
        "gap_stats": _build_gap_stats(m15_after_exclude),
        "weekend_gap_check": _build_weekend_gap_check(m15_after_exclude),
        "hourly_profile": _build_hourly_profile(m15_after_exclude),
        "decode_sanity": _build_decode_sanity(m15_after_exclude),
    }

    with (outdir / "conversion_report.json").open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=False)
        f.write("\n")

    return report


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Convert a raw Dukascopy XAUUSD M15 CSV into DATA_SCHEMA-conformant H1/M15 CSVs."
    )
    p.add_argument("--input", required=True, help="Path to the raw Dukascopy M15 CSV (read-only).")
    p.add_argument("--outdir", required=True, help="Directory to write h1.csv/m15.csv/conversion_report.json into.")
    p.add_argument("--exclude-file", default=None, help="Optional CSV of M15 timestamps to treat as missing.")
    p.add_argument("--symbol", default="XAUUSD", help="Symbol to stamp on every output row (default XAUUSD).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        report = convert(
            Path(args.input),
            Path(args.outdir),
            Path(args.exclude_file) if args.exclude_file else None,
            symbol=args.symbol,
        )
    except ConversionError as e:
        print(f"ConversionError: {e}")
        return 1
    print(json.dumps({"counts": report["counts"], "hours": report["hours"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
