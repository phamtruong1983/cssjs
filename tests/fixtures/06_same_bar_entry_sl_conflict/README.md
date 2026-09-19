# Fixture 06 — Same H1 bar touches both entry and stop-loss

Same base history, zone, ATR, sweep candle (idx 22) and M15 reaction hour
(idx 23, identical to Fixture 04's — reaction fires on the `23:15`
candle) as Fixture 04. `entry = 2000.00`, `stop = 1963.00` (same
derivation as Fixture 01: `1965 - 0.20*10`).

idx 23 is the **activation bar** (M15 reaction fires there); per
`DAO_GAM_RULES.md` Section 5 (`[V1_DECISION]`, resolved) it does **not**
count toward the validity window. idx 23's own range (`low = 2003`) stays
above entry anyway, so it would not have pre-filled the order even if it
did count.

Note: the sweep hour's last M15 candle (`22:45`) is `open=1980, high=2000,
low=1965, close=2000` (same OHLC correction as Fixture 01; caught by
`tests/unit/test_data_schema.py`).

## The conflict bar (idx 24, `2024-01-03T00:00:00Z`) — first candle of the validity window

`open=2015, high=2020, low=1960, close=1990`.

This single H1 candle's range `[1960, 2020]` contains **both**:
- `entry = 2000.00` (within `[1960, 2020]`)
- `stop = 1963.00` (within `[1960, 2020]`)

No M15 (or finer) data is provided for this bar, so there is no way to
know whether price touched `2000.00` before or after `1963.00` within the
hour.

## Expected engine outcome (fully resolved)

Per `DAO_GAM_RULES.md` Section 5 ("Same-bar SL-before-entry",
`[V1_DECISION]`, resolved), the conservative rule applies on idx 24:
**SL is treated as happening first, so no fill occurs on this bar.**
Because the stop-loss level was touched on idx 24, the setup is treated as
invalidated from that point on — no fill is attempted on the remaining
bar of the window either.

Final status: **`EXPIRED`**. Not counted as a trade. This fixture does not
need an idx 25 bar: per the resolved rule, the SL touch on idx 24 already
ends the setup regardless of how many window candles remain.
