# Fixture 06 — Same H1 bar touches both entry and stop-loss

Same base history, zone, ATR, sweep candle (idx 22) and M15 reaction hour
(idx 23, identical to Fixture 04's — reaction fires on the `23:15`
candle) as Fixture 04. `entry = 2000.00`, `stop = 1963.00` (same
derivation as Fixture 01: `1965 - 0.20*10`).

idx 23 (`low = 2003`) stays above entry, same as Fixture 04 — no touch
yet, order not filled during the activation hour.

Note: the sweep hour's last M15 candle (`22:45`) is `open=1980, high=2000,
low=1965, close=2000` (same OHLC correction as Fixture 01; caught by
`tests/unit/test_data_schema.py`).

## The conflict bar (idx 24, `2024-01-03T00:00:00Z`)

`open=2015, high=2020, low=1960, close=1990`.

This single H1 candle's range `[1960, 2020]` contains **both**:
- `entry = 2000.00` (within `[1960, 2020]`)
- `stop = 1963.00` (within `[1960, 2020]`)

No M15 (or finer) data is provided for this bar, so there is no way to
know whether price touched `2000.00` before or after `1963.00` within the
hour.

## Expected engine outcome (scoped narrowly)

Per `DAO_GAM_RULES.md` Section 5 ("Same-bar SL-before-entry"), the
conservative rule applies: **treat idx 24 as no fill**. The order is not
considered triggered on this bar.

This fixture intentionally does **not** assert what happens next (does
the setup become `EXPIRED`, or does it get another chance on a further
bar?), because that depends on an open question not yet resolved:
whether the "2 subsequent H1 candles" validity window (Section 5) is
`{idx 23, idx 24}` (inclusive of the activation bar) or `{idx 24, idx 25}`
(starting strictly after it) — see `docs/DATA_SCHEMA.md` Section 9. No
`idx 25` bar is included in this fixture, precisely so that this
ambiguity is not silently resolved one way or the other by the test data.
If the window is `{idx 23, idx 24}`, this fixture ends in `EXPIRED` (idx
24 was the last bar and did not fill). If it is `{idx 24, idx 25}`, the
outcome is undetermined by this fixture alone and would need an idx 25
bar to test — deliberately left out.
