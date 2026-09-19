"""Tests for fractal swing detection (src/market_structure/swings.py).

Per docs/DAO_GAM_RULES.md Section 3 rule 3 and docs/DATA_SCHEMA.md
Section 4 (zone_center = fractal swing high/low, N=3).
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.market_structure.swings import find_swings  # noqa: E402


def make_df(highs, lows, index=None):
    df = pd.DataFrame({"high": highs, "low": lows})
    if index is not None:
        df.index = index
    return df


# ---------------------------------------------------------------------------
# Basic swing high / swing low
# ---------------------------------------------------------------------------


def test_swing_high_detected_at_center_of_symmetric_peak():
    # highs: 10,20,30,40,50,40,30,20,10 -> peak at index 4 (n=3 window idx1..7)
    highs = [10, 20, 30, 40, 50, 40, 30, 20, 10]
    lows = [5, 15, 25, 35, 45, 35, 25, 15, 5]
    df = make_df(highs, lows)
    result = find_swings(df, n=3)
    assert result["is_swing_high"].tolist() == [False, False, False, False, True, False, False, False, False]


def test_swing_low_detected_at_center_of_symmetric_trough():
    highs = [50, 40, 30, 20, 10, 20, 30, 40, 50]
    lows = [45, 35, 25, 15, 5, 15, 25, 35, 45]
    df = make_df(highs, lows)
    result = find_swings(df, n=3)
    assert result["is_swing_low"].tolist() == [False, False, False, False, True, False, False, False, False]


def test_no_swing_in_monotonic_series():
    highs = list(range(10, 30))
    lows = list(range(0, 20))
    df = make_df(highs, lows)
    result = find_swings(df, n=3)
    assert not result["is_swing_high"].any()
    assert not result["is_swing_low"].any()


# ---------------------------------------------------------------------------
# Tie handling (strict inequality assumption)
# ---------------------------------------------------------------------------


def test_tie_at_equal_high_disqualifies_both_candidates():
    # Two equal peaks at idx 3 and idx 5, both = 50, surrounded by lower bars.
    # window for idx3 (n=1): idx2,3,4 = 40,50,45 -> max=50 unique -> True on its own
    # but with n=3 the window spans both peaks, creating a tie.
    highs = [10, 20, 30, 50, 40, 50, 30, 20, 10]
    lows = [5, 15, 25, 45, 35, 45, 25, 15, 5]
    df = make_df(highs, lows)
    result = find_swings(df, n=3)
    # idx3 window = idx0..6 = [10,20,30,50,40,50,30] -> max=50 appears twice (idx3,idx5) -> tie -> False
    # idx5 window = idx2..8 = [30,50,40,50,30,20,10] -> max=50 appears twice -> tie -> False
    assert result["is_swing_high"].iloc[3] == False
    assert result["is_swing_high"].iloc[5] == False


def test_tie_at_equal_low_disqualifies_both_candidates():
    highs = [50, 40, 30, 10, 20, 10, 30, 40, 50]
    lows = [45, 35, 25, 5, 15, 5, 25, 35, 45]
    df = make_df(highs, lows)
    result = find_swings(df, n=3)
    assert result["is_swing_low"].iloc[3] == False
    assert result["is_swing_low"].iloc[5] == False


def test_flat_series_has_no_swings():
    highs = [20] * 9
    lows = [10] * 9
    df = make_df(highs, lows)
    result = find_swings(df, n=3)
    assert not result["is_swing_high"].any()
    assert not result["is_swing_low"].any()


# ---------------------------------------------------------------------------
# Edge boundaries (first n / last n rows always False)
# ---------------------------------------------------------------------------


def test_first_n_and_last_n_rows_are_always_false():
    highs = [10, 20, 30, 100, 40, 30, 20, 10, 5]
    lows = [5, 15, 25, 90, 35, 25, 15, 5, 1]
    df = make_df(highs, lows)
    n = 3
    result = find_swings(df, n=n)
    assert not result["is_swing_high"].iloc[:n].any()
    assert not result["is_swing_high"].iloc[-n:].any()
    assert not result["is_swing_low"].iloc[:n].any()
    assert not result["is_swing_low"].iloc[-n:].any()


def test_boundary_candidate_with_insufficient_left_side_is_false():
    # A would-be peak at idx 1, but only 1 bar to its left (need n=3) -> False
    highs = [10, 100, 20, 15, 10, 5, 0]
    lows = [5, 90, 10, 5, 0, -5, -10]
    df = make_df(highs, lows)
    result = find_swings(df, n=3)
    assert result["is_swing_high"].iloc[1] == False


# ---------------------------------------------------------------------------
# Insufficient data (shorter than 2n+1) -> all False, no raise
# ---------------------------------------------------------------------------


def test_data_shorter_than_2n_plus_1_returns_all_false():
    # n=3 needs len >= 7; give only 6 rows
    highs = [10, 20, 30, 100, 20, 10]
    lows = [5, 15, 25, 90, 15, 5]
    df = make_df(highs, lows)
    result = find_swings(df, n=3)
    assert len(result) == 6
    assert not result["is_swing_high"].any()
    assert not result["is_swing_low"].any()


def test_empty_dataframe_returns_empty_result():
    df = make_df([], [])
    result = find_swings(df, n=3)
    assert len(result) == 0
    assert list(result.columns) == ["is_swing_high", "is_swing_low"]


def test_exactly_2n_plus_1_rows_can_detect_center():
    # n=3 needs exactly 7 rows for the single center index (3) to qualify
    highs = [10, 20, 30, 100, 30, 20, 10]
    lows = [5, 15, 25, 90, 25, 15, 5]
    df = make_df(highs, lows)
    result = find_swings(df, n=3)
    assert len(result) == 7
    assert result["is_swing_high"].tolist() == [False, False, False, True, False, False, False]


# ---------------------------------------------------------------------------
# Custom n
# ---------------------------------------------------------------------------


def test_custom_n_1():
    highs = [10, 20, 15, 20, 10]
    lows = [5, 15, 10, 15, 5]
    df = make_df(highs, lows)
    result = find_swings(df, n=1)
    # idx1: window idx0,1,2 = [10,20,15] -> max=20 unique -> True
    # idx3: window idx2,3,4 = [15,20,10] -> max=20 unique -> True
    assert result["is_swing_high"].tolist() == [False, True, False, True, False]


def test_custom_n_5():
    highs = list(range(10, 20)) + [100] + list(range(19, 9, -1))
    lows = [h - 5 for h in highs]
    df = make_df(highs, lows)
    result = find_swings(df, n=5)
    peak_idx = highs.index(100)
    assert result["is_swing_high"].iloc[peak_idx] == True
    assert result["is_swing_high"].sum() == 1


# ---------------------------------------------------------------------------
# NaN handling
# ---------------------------------------------------------------------------


def test_nan_in_high_raises():
    highs = [10, 20, np.nan, 20, 10, 5, 0]
    lows = [5, 15, 10, 15, 5, 0, -5]
    df = make_df(highs, lows)
    with pytest.raises(ValueError, match="NaN"):
        find_swings(df, n=3)


def test_nan_in_low_raises():
    highs = [10, 20, 30, 20, 10, 5, 0]
    lows = [5, 15, np.nan, 15, 5, 0, -5]
    df = make_df(highs, lows)
    with pytest.raises(ValueError, match="NaN"):
        find_swings(df, n=3)


# ---------------------------------------------------------------------------
# Missing columns
# ---------------------------------------------------------------------------


def test_missing_high_column_raises():
    df = pd.DataFrame({"low": [5, 15, 25, 35, 45, 35, 25]})
    with pytest.raises(ValueError, match="missing required column"):
        find_swings(df, n=3)


def test_missing_low_column_raises():
    df = pd.DataFrame({"high": [10, 20, 30, 40, 50, 40, 30]})
    with pytest.raises(ValueError, match="missing required column"):
        find_swings(df, n=3)


# ---------------------------------------------------------------------------
# Invalid OHLC (high < low)
# ---------------------------------------------------------------------------


def test_high_below_low_raises():
    highs = [10, 20, 5, 40, 50, 40, 30]
    lows = [5, 15, 25, 35, 45, 35, 25]  # row 2: low(25) > high(5)
    df = make_df(highs, lows)
    with pytest.raises(ValueError, match="high < low"):
        find_swings(df, n=3)


# ---------------------------------------------------------------------------
# n validation
# ---------------------------------------------------------------------------


def test_n_zero_raises():
    df = make_df([10, 20, 30], [5, 15, 25])
    with pytest.raises(ValueError, match="n must be >= 1"):
        find_swings(df, n=0)


def test_n_negative_raises():
    df = make_df([10, 20, 30], [5, 15, 25])
    with pytest.raises(ValueError, match="n must be >= 1"):
        find_swings(df, n=-2)


def test_n_non_int_raises():
    df = make_df([10, 20, 30], [5, 15, 25])
    with pytest.raises(TypeError, match="n must be an int"):
        find_swings(df, n=3.5)


# ---------------------------------------------------------------------------
# Index preserved (including non-default / timestamp index)
# ---------------------------------------------------------------------------


def test_index_preserved_with_datetime_index():
    highs = [10, 20, 30, 100, 30, 20, 10]
    lows = [5, 15, 25, 90, 25, 15, 5]
    idx = pd.date_range("2024-01-02", periods=7, freq="h")
    df = make_df(highs, lows, index=idx)
    result = find_swings(df, n=3)
    pd.testing.assert_index_equal(result.index, df.index)


def test_index_preserved_with_non_contiguous_int_index():
    highs = [10, 20, 30, 100, 30, 20, 10]
    lows = [5, 15, 25, 90, 25, 15, 5]
    idx = [100, 105, 110, 200, 250, 300, 999]
    df = make_df(highs, lows, index=idx)
    result = find_swings(df, n=3)
    pd.testing.assert_index_equal(result.index, df.index)
    # the swing high is still logically at the 4th row (label 200)
    assert result.loc[200, "is_swing_high"] == True


# ---------------------------------------------------------------------------
# Both high and low swing at the same bar (allowed per module assumption)
# ---------------------------------------------------------------------------


def test_same_bar_can_be_both_swing_high_and_swing_low():
    # A single-bar spike: high is a peak AND low is a trough at the same index.
    highs = [10, 15, 12, 100, 12, 15, 10]
    lows = [5, 8, 6, -50, 6, 8, 5]
    df = make_df(highs, lows)
    result = find_swings(df, n=3)
    assert result["is_swing_high"].iloc[3] == True
    assert result["is_swing_low"].iloc[3] == True


# ---------------------------------------------------------------------------
# Look-ahead guarantee
# ---------------------------------------------------------------------------


def test_no_lookahead_swing_confirmed_only_after_n_bars():
    """The swing flag at index i must be identical whether computed on the
    full dataset or on data truncated right after the bar that confirms it
    (i.e. up to and including index i+n). This proves index i's swing
    status never depends on bars beyond i+n, so a causal engine reading
    swings bar-by-bar can safely treat the swing at i as known as soon as
    bar i+n has closed, and not one bar before."""
    n = 3
    highs = [10, 20, 30, 100, 40, 30, 20, 15, 10, 5]
    lows = [5, 15, 25, 90, 35, 25, 15, 10, 5, 0]
    df_full = make_df(highs, lows)
    peak_idx = 3

    full_result = find_swings(df_full, n=n)
    assert full_result["is_swing_high"].iloc[peak_idx] == True

    truncated = df_full.iloc[: peak_idx + n + 1]  # bars 0..6 inclusive
    truncated_result = find_swings(truncated, n=n)

    assert truncated_result["is_swing_high"].iloc[peak_idx] == full_result["is_swing_high"].iloc[peak_idx]
    assert truncated_result["is_swing_low"].iloc[peak_idx] == full_result["is_swing_low"].iloc[peak_idx]


def test_no_lookahead_one_bar_short_cannot_confirm():
    """Truncating at i+n-1 (one bar short of confirmation) must NOT show
    the swing as True -- there aren't enough bars on the right side yet."""
    n = 3
    highs = [10, 20, 30, 100, 40, 30, 20, 15, 10, 5]
    lows = [5, 15, 25, 90, 35, 25, 15, 10, 5, 0]
    df_full = make_df(highs, lows)
    peak_idx = 3

    truncated_short = df_full.iloc[: peak_idx + n]  # bars 0..5, missing bar 6
    truncated_short_result = find_swings(truncated_short, n=n)
    assert truncated_short_result["is_swing_high"].iloc[peak_idx] == False
