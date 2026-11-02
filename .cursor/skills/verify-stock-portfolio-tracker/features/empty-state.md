# Empty state

With no holdings the table area shows `#empty-state` ("No holdings yet") with Import Excel and Load sample data buttons.

## Sub-features

- `empty`: `/?empty=1` (preview only) clears storage; 0 rows, "0 positions", `#empty-state` visible.
- `sample`: "Load sample data" fills the table with the app's built-in sample (5 rows) and saves it.

## How to get to it (user POV)

Open the tracker with no saved data → click Load sample data.

## Driving it with verify.py

- `verify.py compose empty-state --json`.
- Pass means: 0 rows and the empty state, then 5 rows, empty state hidden, and 5 entries in storage.
- Evidence: `evidence/empty-state/empty.png`, `final.png`, `result.json`.

## Gotchas

- The built-in sample uses real tickers (AAPL etc.) from `index.html`, not the EXAMPLE file. It is product code; scenarios only count rows.
