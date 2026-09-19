# Fixture 03 — No M15 reaction → REJECTED_M15_NO_REACTION

Same base history, zone, and sweep candle as Fixture 01 (BUY case) — the
H1 trap is confirmed identically (`close = 2000.0` back inside
`[1999.5, 2000.5]`). The only difference is the M15 candles in the
following hour (23:00–23:45): none of them satisfies all of the BUY
reaction conditions from `DAO_GAM_RULES.md` Section 4.

## M15 window (idx 23's hour)

| Candle | close | body | range | body/range | close_position | a) close>2000 | b) ratio>=0.30 | c) pos>=0.60 | passes? |
|---|---|---|---|---|---|---|---|---|---|
| 23:00 | 2000.5 | 0.5 | 2 | 0.25 | 0.75 | yes | **no** | yes | no |
| 23:15 | 2000.8 | 0.3 | 3 | 0.10 | 0.60 | yes | **no** | yes | no |
| 23:30 | 1999.5 | 1.3 | 4 | 0.325 | 0.375 | **no** | yes | no | no |
| 23:45 | 1998.0 | 1.5 | 4 | 0.375 | 0.25 | **no** | yes | no | no |

No candle in the 4-candle window satisfies conditions a, b, and c
simultaneously.

Note: the sweep hour's last M15 candle (`22:45`) is `open=1980, high=2000,
low=1965, close=2000` (corrected from an invalid earlier draft where
`high < close`; caught by `tests/unit/test_data_schema.py`).

## Expected engine outcome

No tradable signal. Logged with `status = "REJECTED_M15_NO_REACTION"`.
The record still carries the H1 trap-confirmation values (zone, ATR,
sweep_extreme, sweep_amplitude) plus the 4 evaluated M15 candles, per the
logging requirement in `DAO_GAM_RULES.md` Section 4 ("must always log the
raw M15 candles evaluated ... whether or not the reaction fires").
