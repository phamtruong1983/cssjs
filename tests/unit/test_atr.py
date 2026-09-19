"""Tests for the Wilder ATR module (src/indicators/atr.py).

Per docs/DAO_GAM_RULES.md Section 3 rule 4 / rule 7 and
docs/DATA_SCHEMA.md Section 5 (`atr_h1_14`).
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.indicators.atr import atr, true_range  # noqa: E402


def make_df(rows):
    """rows: list of (open, high, low, close) tuples."""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


# ---------------------------------------------------------------------------
# True Range
# ---------------------------------------------------------------------------


def test_true_range_first_row_is_high_minus_low():
    df = make_df(
        [
            (100, 110, 90, 105),
            (105, 115, 95, 108),
        ]
    )
    tr = true_range(df)
    assert tr.iloc[0] == pytest.approx(110 - 90)


def test_true_range_uses_max_of_three_components():
    # Row 1: high-low=115-95=20, |high-prevclose|=|115-105|=10,
    # |low-prevclose|=|95-105|=10 -> max is high-low=20
    df = make_df(
        [
            (100, 110, 90, 105),
            (105, 115, 95, 108),
        ]
    )
    tr = true_range(df)
    assert tr.iloc[1] == pytest.approx(20.0)


def test_true_range_gap_up_uses_high_minus_prev_close():
    # prev close = 100, current bar gaps up: high=130, low=120
    # high-low=10, |high-prevclose|=30, |low-prevclose|=20 -> TR=30
    df = make_df(
        [
            (95, 105, 90, 100),
            (125, 130, 120, 128),
        ]
    )
    tr = true_range(df)
    assert tr.iloc[1] == pytest.approx(30.0)


def test_true_range_gap_down_uses_low_minus_prev_close():
    # prev close = 100, current bar gaps down: high=85, low=70
    # high-low=15, |high-prevclose|=15, |low-prevclose|=30 -> TR=30
    df = make_df(
        [
            (95, 105, 90, 100),
            (80, 85, 70, 75),
        ]
    )
    tr = true_range(df)
    assert tr.iloc[1] == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Wilder smoothing
# ---------------------------------------------------------------------------


def test_atr_first_value_is_sma_of_first_period_tr():
    # 15 bars, constant range=10, no gaps (open == prev close), period=14
    rows = []
    price = 2000
    for i in range(15):
        rows.append((price, price + 10, price, price + 5))
        price += 5  # close becomes next open
    df = make_df(rows)
    result = atr(df, period=14)

    tr = true_range(df)
    expected_first = tr.iloc[:14].mean()
    assert result.iloc[13] == pytest.approx(expected_first)


def test_atr_wilder_recursive_formula():
    rows = []
    price = 2000
    for i in range(16):
        rows.append((price, price + 10, price, price + 5))
        price += 5
    df = make_df(rows)
    result = atr(df, period=14)
    tr = true_range(df)

    prior_atr = tr.iloc[:14].mean()
    expected_atr_14 = (prior_atr * 13 + tr.iloc[14]) / 14
    assert result.iloc[14] == pytest.approx(expected_atr_14)

    expected_atr_15 = (expected_atr_14 * 13 + tr.iloc[15]) / 14
    assert result.iloc[15] == pytest.approx(expected_atr_15)


def test_atr_indices_before_first_atr_are_nan():
    rows = []
    price = 2000
    for i in range(14):
        rows.append((price, price + 10, price, price + 5))
        price += 5
    df = make_df(rows)
    result = atr(df, period=14)
    assert result.iloc[:13].isna().all()
    assert not pd.isna(result.iloc[13])


def test_atr_known_values_manual_walkthrough():
    # Hand-computed fixture: all TR = 10 for every row (constant-width bars,
    # open == prev close), so ATR must equal 10 everywhere it's defined.
    rows = []
    price = 2000
    for i in range(20):
        rows.append((price, price + 10, price, price + 10))
        price += 10
    df = make_df(rows)
    result = atr(df, period=14)
    defined = result.iloc[13:]
    assert defined.tolist() == pytest.approx([10.0] * len(defined))


# ---------------------------------------------------------------------------
# Insufficient rows
# ---------------------------------------------------------------------------


def test_atr_shorter_than_period_is_all_nan():
    rows = [(2000, 2010, 2000, 2005) for _ in range(10)]
    df = make_df(rows)
    result = atr(df, period=14)
    assert len(result) == 10
    assert result.isna().all()


def test_atr_empty_dataframe():
    df = make_df([])
    result = atr(df, period=14)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# Missing columns
# ---------------------------------------------------------------------------


def test_true_range_missing_column_raises():
    df = pd.DataFrame({"open": [100, 105], "high": [110, 115], "close": [105, 108]})
    with pytest.raises(ValueError, match="missing required column"):
        true_range(df)


def test_atr_missing_column_raises():
    df = pd.DataFrame({"open": [100, 105], "high": [110, 115], "close": [105, 108]})
    with pytest.raises(ValueError, match="missing required column"):
        atr(df)


# ---------------------------------------------------------------------------
# NaN handling
# ---------------------------------------------------------------------------


def test_true_range_nan_in_high_raises():
    df = make_df([(100, np.nan, 90, 105), (105, 115, 95, 108)])
    with pytest.raises(ValueError, match="NaN"):
        true_range(df)


def test_true_range_nan_in_low_raises():
    df = make_df([(100, 110, np.nan, 105), (105, 115, 95, 108)])
    with pytest.raises(ValueError, match="NaN"):
        true_range(df)


def test_true_range_nan_in_close_raises():
    df = make_df([(100, 110, 90, np.nan), (105, 115, 95, 108)])
    with pytest.raises(ValueError, match="NaN"):
        true_range(df)


# ---------------------------------------------------------------------------
# Invalid OHLC
# ---------------------------------------------------------------------------


def test_invalid_ohlc_high_below_low_raises():
    df = make_df([(100, 90, 95, 92)])  # high < low
    with pytest.raises(ValueError, match="invalid OHLC"):
        true_range(df)


def test_invalid_ohlc_high_below_close_raises():
    df = make_df([(100, 100, 90, 105)])  # close > high
    with pytest.raises(ValueError, match="invalid OHLC"):
        true_range(df)


def test_invalid_ohlc_low_above_open_raises():
    df = make_df([(85, 110, 90, 100)])  # open < low
    with pytest.raises(ValueError, match="invalid OHLC"):
        true_range(df)


def test_invalid_ohlc_high_below_open_raises():
    df = make_df([(120, 110, 90, 100)])  # open > high
    with pytest.raises(ValueError, match="invalid OHLC"):
        true_range(df)


def test_valid_ohlc_without_open_column_passes():
    df = pd.DataFrame({"high": [110, 115], "low": [90, 95], "close": [105, 108]})
    tr = true_range(df)
    assert not tr.isna().any()


# ---------------------------------------------------------------------------
# Period validation
# ---------------------------------------------------------------------------


def test_period_zero_raises():
    df = make_df([(100, 110, 90, 105)])
    with pytest.raises(ValueError, match="period must be >= 1"):
        atr(df, period=0)


def test_period_negative_raises():
    df = make_df([(100, 110, 90, 105)])
    with pytest.raises(ValueError, match="period must be >= 1"):
        atr(df, period=-5)


def test_period_non_int_raises():
    df = make_df([(100, 110, 90, 105)])
    with pytest.raises(TypeError, match="period must be an int"):
        atr(df, period=14.5)


# ---------------------------------------------------------------------------
# Custom period
# ---------------------------------------------------------------------------


def test_custom_period_5():
    rows = []
    price = 2000
    for i in range(8):
        rows.append((price, price + 10, price, price + 10))
        price += 10
    df = make_df(rows)
    result = atr(df, period=5)
    tr = true_range(df)

    assert result.iloc[:4].isna().all()
    expected_first = tr.iloc[:5].mean()
    assert result.iloc[4] == pytest.approx(expected_first)

    expected_next = (expected_first * 4 + tr.iloc[5]) / 5
    assert result.iloc[5] == pytest.approx(expected_next)


def test_period_1_equals_true_range():
    rows = [(2000, 2010, 1995, 2005), (2005, 2020, 2000, 2015), (2015, 2018, 2008, 2010)]
    df = make_df(rows)
    result = atr(df, period=1)
    tr = true_range(df)
    pd.testing.assert_series_equal(result, tr, check_names=False)


# ---------------------------------------------------------------------------
# Dao Gam fixture cross-check (docs/DATA_SCHEMA.md Section 5 atr_h1_14)
# ---------------------------------------------------------------------------


def test_atr_matches_fixture_01_documented_value():
    """tests/fixtures/01_buy_valid/README.md documents atr_h1_14 = 10.00
    "at idx 22 (computed from the 14 preceding bars)" -- i.e. the ATR value
    a signal engine would reference to evaluate the sweep candle (idx 22)
    is the ATR as of the close of idx 21 (the last of the 14 preceding
    bars), not an ATR that already folds in idx 22's own (huge) True
    Range. This module computes standard Wilder ATR, where atr[i] does
    include bar i's own TR, so that reference value is atr_series.iloc[21].
    """
    fixtures_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "01_buy_valid"
    )
    df = pd.read_csv(os.path.join(fixtures_dir, "h1.csv"))
    result = atr(df, period=14)
    assert result.iloc[21] == pytest.approx(10.0)
