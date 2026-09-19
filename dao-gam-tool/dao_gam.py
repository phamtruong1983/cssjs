"""Dao Gam ("Dagger") stop-hunt reversal detector.

Implements the pattern described in "Forex Sinh Tu Ky Thu - Tap 2":

  1. Price makes a strong impulsive move that establishes a clear
     support/resistance level (a swing high or low).
  2. Price returns to that level later and, on a high-range candle, pierces
     through it -- this is the move that drags the crowd into breakout
     trades in the direction of the piercing wick (and triggers/attracts a
     cluster of stop-losses just beyond it).
  3. Price then snaps back the other way, closing back on the origin side
     of the level ("fake breakout" / stop-hunt candle) -- the crowd that
     just went all-in the breakout direction is now trapped.

  Trade idea: fade the piercing move.
    entry  = the pierced level (retest zone)
    stop   = beyond the wick that did the piercing, + buffer
    tp1    = the nearest prior swing point on the entry side (the level the
             crowd was aiming for before getting trapped)
    tp2    = tp1 +/- the amplitude of the stop-hunt wick (how far price
             overshot the level), continuing in the trade direction

This module only encodes the mechanical part of the pattern (swing
detection, piercing-and-reject candle, level distances). The book is
explicit that the real edge is reading crowd psychology -- treat this as a
candidate-signal screener, not a black box.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd


@dataclass
class Signal:
    time: datetime
    direction: str  # "buy" or "sell"
    level: float  # the support/resistance level that got hunted
    entry: float
    stop: float
    tp1: float
    tp2: float
    wick_extreme: float  # the extreme of the stop-hunt candle
    amplitude: float  # |wick_extreme - level|

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward1(self) -> float:
        return abs(self.tp1 - self.entry)

    @property
    def reward2(self) -> float:
        return abs(self.tp2 - self.entry)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["risk"] = self.risk
        d["rr1"] = round(self.reward1 / self.risk, 2) if self.risk else float("nan")
        d["rr2"] = round(self.reward2 / self.risk, 2) if self.risk else float("nan")
        return d


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period).mean()


def _swing_points(df: pd.DataFrame, lookback: int = 3) -> tuple[pd.Series, pd.Series]:
    """Fractal-style swing highs/lows: a bar's high/low is more extreme than
    `lookback` bars on either side."""
    highs = df["high"]
    lows = df["low"]
    is_swing_high = pd.Series(False, index=df.index)
    is_swing_low = pd.Series(False, index=df.index)
    n = len(df)
    for i in range(lookback, n - lookback):
        window_h = highs.iloc[i - lookback : i + lookback + 1]
        window_l = lows.iloc[i - lookback : i + lookback + 1]
        if highs.iloc[i] == window_h.max() and (window_h == window_h.max()).sum() == 1:
            is_swing_high.iloc[i] = True
        if lows.iloc[i] == window_l.min() and (window_l == window_l.min()).sum() == 1:
            is_swing_low.iloc[i] = True
    return is_swing_high, is_swing_low


def find_signals(
    df: pd.DataFrame,
    swing_lookback: int = 3,
    atr_period: int = 14,
    min_pierce_atr: float = 0.25,
    reject_close_atr: float = 0.15,
    stop_buffer_atr: float = 0.2,
) -> list[Signal]:
    """Scan an OHLC dataframe (indexed by time, columns open/high/low/close)
    for Dao Gam stop-hunt setups.

    Parameters
    ----------
    swing_lookback: bars on each side used to confirm a swing high/low.
    atr_period: ATR window used to size "meaningful" pierces/rejections.
    min_pierce_atr: minimum wick pierce beyond the level, in ATR units, to
        count as a real hunt (filters noise).
    reject_close_atr: how close the candle must close back to (or past) the
        level, in ATR units, to count as a rejection rather than a genuine
        breakout.
    stop_buffer_atr: extra buffer beyond the wick extreme for the stop-loss.
    """
    df = df.copy()
    df["atr"] = _atr(df, atr_period)
    is_high, is_low = _swing_points(df, swing_lookback)

    swing_highs = df["high"].where(is_high).ffill()
    swing_lows = df["low"].where(is_low).ffill()
    # previous swing (the one before the level currently referenced), used as TP1
    prev_swing_high = df["high"].where(is_high).ffill().shift(1).where(is_high.cumsum().shift(1) > 0)
    prev_swing_low = df["low"].where(is_low).ffill().shift(1).where(is_low.cumsum().shift(1) > 0)

    signals: list[Signal] = []

    for i in range(swing_lookback, len(df)):
        row = df.iloc[i]
        atr = row["atr"]
        if not np.isfinite(atr) or atr <= 0:
            continue

        level_res = swing_highs.iloc[i - 1]  # resistance to test
        level_sup = swing_lows.iloc[i - 1]  # support to test

        # --- SELL setup: price pierces below a support level then closes
        #     back above it (crowd rushed to sell the breakdown -> trapped).
        if np.isfinite(level_sup):
            pierce = level_sup - row["low"]
            if pierce >= min_pierce_atr * atr and row["close"] >= level_sup - reject_close_atr * atr:
                amplitude = level_sup - row["low"]
                tp1 = prev_swing_high.iloc[i] if np.isfinite(prev_swing_high.iloc[i]) else swing_highs.iloc[i - 1] + amplitude
                signals.append(
                    Signal(
                        time=df.index[i],
                        direction="buy",
                        level=level_sup,
                        entry=level_sup,
                        stop=row["low"] - stop_buffer_atr * atr,
                        tp1=tp1,
                        tp2=tp1 + amplitude,
                        wick_extreme=row["low"],
                        amplitude=amplitude,
                    )
                )

        # --- BUY setup: price pierces above a resistance level then closes
        #     back below it (crowd rushed to buy the breakout -> trapped).
        if np.isfinite(level_res):
            pierce = row["high"] - level_res
            if pierce >= min_pierce_atr * atr and row["close"] <= level_res + reject_close_atr * atr:
                amplitude = row["high"] - level_res
                tp1 = prev_swing_low.iloc[i] if np.isfinite(prev_swing_low.iloc[i]) else swing_lows.iloc[i - 1] - amplitude
                signals.append(
                    Signal(
                        time=df.index[i],
                        direction="sell",
                        level=level_res,
                        entry=level_res,
                        stop=row["high"] + stop_buffer_atr * atr,
                        tp1=tp1,
                        tp2=tp1 - amplitude,
                        wick_extreme=row["high"],
                        amplitude=amplitude,
                    )
                )

    return signals


def signals_to_frame(signals: list[Signal]) -> pd.DataFrame:
    if not signals:
        return pd.DataFrame(
            columns=["time", "direction", "level", "entry", "stop", "tp1", "tp2", "risk", "rr1", "rr2"]
        )
    return pd.DataFrame([s.as_dict() for s in signals]).set_index("time")
