"""Schema-level tests for Dao Gam V1 fixtures.

Only tests OHLCV structural validity (docs/DATA_SCHEMA.md). Does not test
any zone/sweep/signal logic -- that engine has not been built yet.
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schema import validate_ohlcv  # noqa: E402

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")

ALL_FIXTURE_H1_CSVS = [
    os.path.join(FIXTURES_DIR, name, "h1.csv")
    for name in sorted(os.listdir(FIXTURES_DIR))
    if os.path.isdir(os.path.join(FIXTURES_DIR, name))
]

ALL_FIXTURE_M15_CSVS = [
    os.path.join(FIXTURES_DIR, name, "m15.csv")
    for name in sorted(os.listdir(FIXTURES_DIR))
    if os.path.isfile(os.path.join(FIXTURES_DIR, name, "m15.csv"))
]


@pytest.mark.parametrize("path", ALL_FIXTURE_H1_CSVS)
def test_fixture_h1_files_are_valid(path):
    df = pd.read_csv(path)
    errors = validate_ohlcv(df)
    assert errors == [], f"{path}: {errors}"


@pytest.mark.parametrize("path", ALL_FIXTURE_M15_CSVS)
def test_fixture_m15_files_are_valid(path):
    df = pd.read_csv(path)
    errors = validate_ohlcv(df)
    assert errors == [], f"{path}: {errors}"


def test_valid_minimal_dataframe_has_no_errors():
    df = pd.DataFrame(
        {
            "timestamp": ["2024-01-02T00:00:00Z", "2024-01-02T01:00:00Z"],
            "symbol": ["XAUUSD", "XAUUSD"],
            "timeframe": ["H1", "H1"],
            "open": [2050, 2040],
            "high": [2060, 2050],
            "low": [2040, 2030],
            "close": [2045, 2035],
            "volume": [0, 0],
        }
    )
    assert validate_ohlcv(df) == []


def test_missing_required_column_is_reported():
    df = pd.DataFrame(
        {
            "timestamp": ["2024-01-02T00:00:00Z"],
            "symbol": ["XAUUSD"],
            # "timeframe" column omitted on purpose
            "open": [2050],
            "high": [2060],
            "low": [2040],
            "close": [2045],
        }
    )
    errors = validate_ohlcv(df)
    assert len(errors) == 1
    assert "timeframe" in errors[0]


def test_non_increasing_timestamp_is_reported():
    df = pd.DataFrame(
        {
            "timestamp": ["2024-01-02T01:00:00Z", "2024-01-02T00:00:00Z"],
            "symbol": ["XAUUSD", "XAUUSD"],
            "timeframe": ["H1", "H1"],
            "open": [2050, 2040],
            "high": [2060, 2050],
            "low": [2040, 2030],
            "close": [2045, 2035],
        }
    )
    errors = validate_ohlcv(df)
    assert any("not strictly increasing" in e for e in errors)


def test_duplicate_timestamp_is_reported():
    df = pd.DataFrame(
        {
            "timestamp": ["2024-01-02T00:00:00Z", "2024-01-02T00:00:00Z"],
            "symbol": ["XAUUSD", "XAUUSD"],
            "timeframe": ["H1", "H1"],
            "open": [2050, 2040],
            "high": [2060, 2050],
            "low": [2040, 2030],
            "close": [2045, 2035],
        }
    )
    errors = validate_ohlcv(df)
    assert any("duplicate" in e for e in errors)


@pytest.mark.parametrize(
    "field,value",
    [("high", 2000), ("low", 2100)],
)
def test_invalid_ohlc_is_reported(field, value):
    row = {
        "timestamp": ["2024-01-02T00:00:00Z"],
        "symbol": ["XAUUSD"],
        "timeframe": ["H1"],
        "open": [2050],
        "high": [2060],
        "low": [2040],
        "close": [2045],
    }
    row[field] = [value]
    df = pd.DataFrame(row)
    errors = validate_ohlcv(df)
    assert any("invalid OHLC" in e for e in errors)


def test_volume_missing_column_is_valid():
    df = pd.DataFrame(
        {
            "timestamp": ["2024-01-02T00:00:00Z"],
            "symbol": ["XAUUSD"],
            "timeframe": ["H1"],
            "open": [2050],
            "high": [2060],
            "low": [2040],
            "close": [2045],
        }
    )
    assert validate_ohlcv(df) == []


def test_volume_zero_is_valid():
    df = pd.DataFrame(
        {
            "timestamp": ["2024-01-02T00:00:00Z"],
            "symbol": ["XAUUSD"],
            "timeframe": ["H1"],
            "open": [2050],
            "high": [2060],
            "low": [2040],
            "close": [2045],
            "volume": [0],
        }
    )
    assert validate_ohlcv(df) == []


def test_volume_nan_is_valid():
    df = pd.DataFrame(
        {
            "timestamp": ["2024-01-02T00:00:00Z"],
            "symbol": ["XAUUSD"],
            "timeframe": ["H1"],
            "open": [2050],
            "high": [2060],
            "low": [2040],
            "close": [2045],
            "volume": [float("nan")],
        }
    )
    assert validate_ohlcv(df) == []


def test_negative_volume_is_reported():
    df = pd.DataFrame(
        {
            "timestamp": ["2024-01-02T00:00:00Z"],
            "symbol": ["XAUUSD"],
            "timeframe": ["H1"],
            "open": [2050],
            "high": [2060],
            "low": [2040],
            "close": [2045],
            "volume": [-5],
        }
    )
    errors = validate_ohlcv(df)
    assert any("negative volume" in e for e in errors)
