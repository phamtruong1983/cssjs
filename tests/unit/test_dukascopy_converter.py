"""Tests for the Dukascopy XAUUSD M15 -> H1/M15 converter
(src/data/dukascopy_converter.py).

Uses only small, hand-computed synthetic CSVs written to tmp_path --
never the real Dukascopy dataset. Per docs/DATA_SCHEMA.md Section 1-3.
"""
import hashlib
import json
import os
import re
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.data.dukascopy_converter import ConversionError, convert  # noqa: E402
from tests.schema import validate_ohlcv  # noqa: E402

HEADER = "Etc/UTC,Open,High,Low,Close,Volume\n"


def write_input(tmp_path, rows, name="input.csv"):
    path = tmp_path / name
    path.write_text(HEADER + "\n".join(rows) + ("\n" if rows else ""))
    return path


def row(ts, o, h, l, c, v):
    return f"{ts},{o},{h},{l},{c},{v}"


# ---------------------------------------------------------------------------
# Hard errors
# ---------------------------------------------------------------------------


def test_wrong_header_raises(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("Timestamp,O,H,L,C,V\n" + row("2024-01-01T08:00:00+00:00", 1, 2, 1, 1, 10) + "\n")
    with pytest.raises(ConversionError, match="header"):
        convert(path, tmp_path / "out")


def test_nonzero_offset_raises(tmp_path):
    path = write_input(tmp_path, [row("2024-01-01T08:00:00+02:00", 1, 2, 1, 1, 10)])
    with pytest.raises(ConversionError, match="non-zero UTC offset"):
        convert(path, tmp_path / "out")


def test_unparseable_timestamp_raises(tmp_path):
    path = write_input(tmp_path, [row("not-a-timestamp", 1, 2, 1, 1, 10)])
    with pytest.raises(ConversionError, match="could not be parsed"):
        convert(path, tmp_path / "out")


def test_misaligned_minute_raises(tmp_path):
    path = write_input(tmp_path, [row("2024-01-01T08:05:00+00:00", 1, 2, 1, 1, 10)])
    with pytest.raises(ConversionError, match="not aligned"):
        convert(path, tmp_path / "out")


def test_duplicate_timestamp_raises(tmp_path):
    path = write_input(
        tmp_path,
        [
            row("2024-01-01T08:00:00+00:00", 100, 101, 99, 100, 10),
            row("2024-01-01T08:00:00+00:00", 100, 101, 99, 100, 10),
        ],
    )
    with pytest.raises(ConversionError, match="duplicate timestamp"):
        convert(path, tmp_path / "out")


def test_out_of_order_timestamp_raises(tmp_path):
    path = write_input(
        tmp_path,
        [
            row("2024-01-01T08:15:00+00:00", 100, 101, 99, 100, 10),
            row("2024-01-01T08:00:00+00:00", 100, 101, 99, 100, 10),
        ],
    )
    with pytest.raises(ConversionError, match="out of order"):
        convert(path, tmp_path / "out")


# ---------------------------------------------------------------------------
# Rounding (ROUND_HALF_UP)
# ---------------------------------------------------------------------------


def test_rounding_half_up_hand_computed(tmp_path):
    rows = [
        # open=2062.605 -> 2062.61 (half up)
        row("2024-01-01T11:00:00+00:00", "2062.605", "2065.00", "2060.00", "2063.00", 10),
        # close=2062.604 -> 2062.60 (round down)
        row("2024-01-01T11:15:00+00:00", "2063.00", "2065.00", "2060.50", "2062.604", 10),
        # open=2062.595 -> 2062.60 (half up)
        row("2024-01-01T11:30:00+00:00", "2062.595", "2065.00", "2060.00", "2063.00", 10),
        row("2024-01-01T11:45:00+00:00", "2063.00", "2065.00", "2060.00", "2064.00", 10),
    ]
    path = write_input(tmp_path, rows)
    report = convert(path, tmp_path / "out")

    m15 = pd.read_csv(tmp_path / "out" / "m15.csv")
    assert m15.loc[0, "open"] == pytest.approx(2062.61)
    assert m15.loc[1, "close"] == pytest.approx(2062.60)
    assert m15.loc[2, "open"] == pytest.approx(2062.60)

    assert report["rounding"]["count_rounded"] == 3
    assert report["rounding"]["max_deviation"] == "0.005"


# ---------------------------------------------------------------------------
# Soft errors: excluded rows, listed with line + reason
# ---------------------------------------------------------------------------


def test_invalid_ohlc_row_excluded_and_listed(tmp_path):
    rows = [
        row("2024-01-01T08:00:00+00:00", 100, 101, 99, 100, 10),
        # high(100) < close(105) -> invalid OHLC
        row("2024-01-01T08:15:00+00:00", 100, 100, 99, 105, 10),
    ]
    path = write_input(tmp_path, rows)
    report = convert(path, tmp_path / "out")

    m15 = pd.read_csv(tmp_path / "out" / "m15.csv")
    assert len(m15) == 1
    assert report["rows_excluded"]["by_reason"] == {"invalid_ohlc": 1}
    excluded_rows = report["rows_excluded"]["rows"]
    assert len(excluded_rows) == 1
    assert excluded_rows[0]["line"] == 3  # header=1, row1=2, row2=3
    assert excluded_rows[0]["reason"] == "invalid_ohlc"


def test_empty_cell_row_excluded_and_listed(tmp_path):
    rows = [
        row("2024-01-01T08:00:00+00:00", 100, 101, 99, 100, 10),
        "2024-01-01T08:15:00+00:00,,101,99,100,10",
    ]
    path = write_input(tmp_path, rows)
    report = convert(path, tmp_path / "out")

    m15 = pd.read_csv(tmp_path / "out" / "m15.csv")
    assert len(m15) == 1
    assert report["rows_excluded"]["by_reason"] == {"non_numeric_or_empty": 1}
    assert report["rows_excluded"]["rows"][0]["line"] == 3


def test_non_positive_price_row_excluded_and_listed(tmp_path):
    rows = [
        row("2024-01-01T08:00:00+00:00", 100, 101, 99, 100, 10),
        row("2024-01-01T08:15:00+00:00", 0, 101, 99, 100, 10),
    ]
    path = write_input(tmp_path, rows)
    report = convert(path, tmp_path / "out")

    m15 = pd.read_csv(tmp_path / "out" / "m15.csv")
    assert len(m15) == 1
    assert report["rows_excluded"]["by_reason"] == {"non_positive_price": 1}


def test_negative_volume_row_excluded_and_listed(tmp_path):
    rows = [
        row("2024-01-01T08:00:00+00:00", 100, 101, 99, 100, 10),
        row("2024-01-01T08:15:00+00:00", 100, 101, 99, 100, -5),
    ]
    path = write_input(tmp_path, rows)
    report = convert(path, tmp_path / "out")

    m15 = pd.read_csv(tmp_path / "out" / "m15.csv")
    assert len(m15) == 1
    assert report["rows_excluded"]["by_reason"] == {"negative_volume": 1}


# ---------------------------------------------------------------------------
# H1 aggregation
# ---------------------------------------------------------------------------


def test_complete_hour_aggregation_hand_computed(tmp_path):
    rows = [
        row("2024-01-01T08:00:00+00:00", "100.00", "102.00", "99.00", "101.00", 10),
        row("2024-01-01T08:15:00+00:00", "101.00", "103.00", "100.50", "102.50", 20),
        row("2024-01-01T08:30:00+00:00", "102.50", "104.00", "101.00", "103.00", 30),
        row("2024-01-01T08:45:00+00:00", "103.00", "103.50", "98.00", "99.50", 40),
    ]
    path = write_input(tmp_path, rows)
    report = convert(path, tmp_path / "out")

    h1 = pd.read_csv(tmp_path / "out" / "h1.csv")
    assert len(h1) == 1
    r = h1.iloc[0]
    assert r["timestamp"] == "2024-01-01T08:00:00Z"
    assert r["open"] == pytest.approx(100.00)  # open of :00
    assert r["high"] == pytest.approx(104.00)  # max of all 4 highs
    assert r["low"] == pytest.approx(98.00)  # min of all 4 lows
    assert r["close"] == pytest.approx(99.50)  # close of :45
    assert r["volume"] == 100  # 10+20+30+40
    assert report["hours"]["complete"] == 1
    assert report["hours"]["incomplete"] == 0
    assert report["partial_hours"] == []


def test_incomplete_hour_excluded_from_h1_kept_in_m15_and_listed(tmp_path):
    rows = [
        row("2024-01-01T09:00:00+00:00", "100.00", "102.00", "99.00", "101.00", 10),
        row("2024-01-01T09:15:00+00:00", "101.00", "103.00", "100.50", "102.50", 20),
        row("2024-01-01T09:30:00+00:00", "102.50", "104.00", "101.00", "103.00", 30),
        # :45 missing -> incomplete hour
    ]
    path = write_input(tmp_path, rows)
    report = convert(path, tmp_path / "out")

    h1 = pd.read_csv(tmp_path / "out" / "h1.csv")
    m15 = pd.read_csv(tmp_path / "out" / "m15.csv")
    assert len(h1) == 0
    assert len(m15) == 3
    assert report["hours"]["complete"] == 0
    assert report["hours"]["incomplete"] == 1
    assert report["partial_hours"] == [
        {"hour": "2024-01-01T09:00:00Z", "present_minutes": [0, 15, 30], "missing_minutes": [45]}
    ]


# ---------------------------------------------------------------------------
# --exclude-file
# ---------------------------------------------------------------------------


def test_exclude_file_removes_candle_and_its_hour(tmp_path):
    rows = [
        row("2024-01-01T12:00:00+00:00", "100.00", "102.00", "99.00", "101.00", 10),
        row("2024-01-01T12:15:00+00:00", "101.00", "103.00", "100.50", "102.50", 20),
        row("2024-01-01T12:30:00+00:00", "102.50", "104.00", "101.00", "103.00", 30),
        row("2024-01-01T12:45:00+00:00", "103.00", "103.50", "98.00", "99.50", 40),
    ]
    path = write_input(tmp_path, rows)

    exclude_path = tmp_path / "exclude.csv"
    exclude_path.write_text("2024-01-01T12:15:00+00:00\n2024-01-01T13:00:00+00:00\n")  # 2nd line matches nothing

    report = convert(path, tmp_path / "out", exclude_path=exclude_path)

    m15 = pd.read_csv(tmp_path / "out" / "m15.csv")
    h1 = pd.read_csv(tmp_path / "out" / "h1.csv")
    assert len(m15) == 3
    assert "2024-01-01T12:15:00Z" not in set(m15["timestamp"])
    assert len(h1) == 0
    assert report["exclude_file"]["excluded_candles"] == 1
    assert report["exclude_file"]["unmatched_lines"] == 1
    assert report["partial_hours"] == [
        {"hour": "2024-01-01T12:00:00Z", "present_minutes": [0, 30, 45], "missing_minutes": [15]}
    ]


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


def test_output_matches_data_schema_and_validate_ohlcv(tmp_path):
    rows = [
        row("2024-01-01T08:00:00+00:00", "100.00", "102.00", "99.00", "101.00", 10),
        row("2024-01-01T08:15:00+00:00", "101.00", "103.00", "100.50", "102.50", 20),
        row("2024-01-01T08:30:00+00:00", "102.50", "104.00", "101.00", "103.00", 30),
        row("2024-01-01T08:45:00+00:00", "103.00", "103.50", "98.00", "99.50", 40),
    ]
    path = write_input(tmp_path, rows)
    convert(path, tmp_path / "out")

    for name, timeframe in (("h1.csv", "H1"), ("m15.csv", "M15")):
        df = pd.read_csv(tmp_path / "out" / name)
        assert list(df.columns) == ["timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume"]
        assert (df["symbol"] == "XAUUSD").all()
        assert (df["timeframe"] == timeframe).all()
        assert df["timestamp"].apply(lambda s: bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", s))).all()
        errors = validate_ohlcv(df)
        assert errors == []

    h1 = pd.read_csv(tmp_path / "out" / "h1.csv")
    m15 = pd.read_csv(tmp_path / "out" / "m15.csv")
    assert h1.loc[0, "open"] == pytest.approx(m15.loc[0, "open"])
    assert h1.loc[0, "close"] == pytest.approx(m15.loc[3, "close"])
    assert h1.loc[0, "high"] == pytest.approx(m15["high"].max())
    assert h1.loc[0, "low"] == pytest.approx(m15["low"].min())


# ---------------------------------------------------------------------------
# Gap classification + weekend_gap_check (hand-computed, 2-week synthetic set)
# ---------------------------------------------------------------------------


def test_gap_classification_and_weekend_gap_check_two_weeks(tmp_path):
    # Week 1: Friday 2024-01-05 last candle 21:45, then weekend gap to
    # Sunday 2024-01-07 22:00 (gap = 48h15m, ">24h").
    # Week 2: Friday 2024-01-12 last candle 21:45, then weekend gap to
    # Sunday 2024-01-14 22:00 (same weekday/time pattern both weeks).
    # Consecutive-pair gaps, hand-computed:
    #   08:00->08:15 (same day)            = 0.25h  -> "<=1h"
    #   08:15->21:45 (same day)            = 13.5h  -> "1-24h"
    #   21:45(01-05)->22:00(01-07)         = 48.25h -> ">24h" (weekend 1)
    #   22:00(01-07)->21:45(01-12)         = 119.75h -> ">24h" (no M15 data
    #     for the weekdays in between in this minimal fixture -- also
    #     classified ">24h" by the same >24h rule, not excluded as
    #     "not a real weekend": the spec applies the rule to every gap
    #     >24h, not just Friday->Sunday ones)
    #   21:45(01-12)->22:00(01-14)         = 48.25h -> ">24h" (weekend 2)
    rows = [
        row("2024-01-05T08:00:00+00:00", "100.00", "101.00", "99.00", "100.50", 10),
        row("2024-01-05T08:15:00+00:00", "100.50", "101.50", "100.00", "101.00", 10),
        row("2024-01-05T21:45:00+00:00", "100.00", "101.00", "99.00", "100.00", 10),
        row("2024-01-07T22:00:00+00:00", "100.00", "101.00", "99.00", "100.50", 10),
        row("2024-01-12T21:45:00+00:00", "100.00", "101.00", "99.00", "100.00", 10),
        row("2024-01-14T22:00:00+00:00", "100.00", "101.00", "99.00", "100.50", 10),
    ]
    path = write_input(tmp_path, rows)
    report = convert(path, tmp_path / "out")

    gap_stats = report["gap_stats"]
    assert gap_stats["buckets"] == {"<=1h": 1, "1-24h": 1, ">24h": 3}

    wk = report["weekend_gap_check"]
    assert len(wk["events"]) == 3
    e0, e1, e2 = wk["events"]
    assert e0["before"] == {
        "timestamp": "2024-01-05T21:45:00Z",
        "weekday": "Friday",
        "time_utc": "21:45",
        "date": "2024-01-05",
    }
    assert e0["after"] == {
        "timestamp": "2024-01-07T22:00:00Z",
        "weekday": "Sunday",
        "time_utc": "22:00",
        "date": "2024-01-07",
    }
    assert e2["before"] == {
        "timestamp": "2024-01-12T21:45:00Z",
        "weekday": "Friday",
        "time_utc": "21:45",
        "date": "2024-01-12",
    }
    assert e2["after"] == {
        "timestamp": "2024-01-14T22:00:00Z",
        "weekday": "Sunday",
        "time_utc": "22:00",
        "date": "2024-01-14",
    }
    # before-times: 21:45, 22:00, 21:45 -> mode "21:45"
    # after-times:  22:00, 21:45, 22:00 -> mode "22:00"
    assert wk["monthly_most_common_times"]["2024-01"] == {
        "most_common_before_time_utc": "21:45",
        "most_common_after_time_utc": "22:00",
    }


# ---------------------------------------------------------------------------
# Determinism + input file untouched
# ---------------------------------------------------------------------------


def test_deterministic_two_runs_produce_identical_output(tmp_path):
    rows = [
        row("2024-01-01T08:00:00+00:00", "100.00", "102.00", "99.00", "101.00", 10),
        row("2024-01-01T08:15:00+00:00", "101.00", "103.00", "100.50", "102.50", 20),
        row("2024-01-01T08:30:00+00:00", "102.50", "104.00", "101.00", "103.00", 30),
        row("2024-01-01T08:45:00+00:00", "103.00", "103.50", "98.00", "99.50", 40),
    ]
    path = write_input(tmp_path, rows)
    before_sha = hashlib.sha256(path.read_bytes()).hexdigest()

    convert(path, tmp_path / "out1")
    convert(path, tmp_path / "out2")

    after_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert before_sha == after_sha  # input never modified

    for name in ("h1.csv", "m15.csv", "conversion_report.json"):
        assert (tmp_path / "out1" / name).read_bytes() == (tmp_path / "out2" / name).read_bytes()
