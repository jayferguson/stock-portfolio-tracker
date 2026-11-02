# Add holding

The "Add stock" toolbar button opens a dialog (`#modal`) to add a position by symbol, name, shares, price and change %.

## Sub-features

- `open`: `[role=toolbar] button:has-text('Add stock')` shows `#modal`, title "Add stock", focus on `#modal-symbol`.
- `save`: `#modal-save-btn` submits; the symbol is upper-cased; the dialog closes.
- `effects`: a 6th row, "6 positions", the new total, and the entry in `localStorage.stockHoldings_v1`.

## How to get to it (user POV)

Toolbar → Add stock → fill Symbol, Name, Shares, Price, Change % → Save.

## Driving it with verify.py

- `verify.py compose add-holding --json`.
- Pass means: EXZ, 10 × $50 → 6 rows, "6 positions", total "$53,114.10", and storage holds `{symbol: "EXZ", shares: 10, currentPrice: 50}`.
- Evidence: `evidence/add-holding/dialog-filled.png`, `added.png`, `result.json`.

## Gotchas

- `dev/preview.py` re-seeds storage on every load of `/`, so a reload wipes the added row. Persistence is proven by reading `localStorage`, not by reloading.
- Use EXAMPLE-style symbols (EX*) in scenarios; this repo is public.
