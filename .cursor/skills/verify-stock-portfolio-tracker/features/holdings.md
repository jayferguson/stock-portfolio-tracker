# Holdings table

The main view: one row per holding with editable shares/price/change %, computed Change $, Day's gain/loss and Market value, a totals footer, and summary cards above (total value, positions, today's P/L, movers).

## Sub-features

- `rows`: `#table-body tr[data-id=exN]`, one per holding in `stockHoldings_v1`.
- `totals`: `#total-value`, `#total-positions` ("5 positions"), `#day-pl`, `#movers`, and the `#table-footer` "Portfolio totals" row.
- `market pill`: `#last-updated-text`, which reads "Weekend • Updates paused" on Saturday/Sunday ET.
- `sort`: each `#table-head th[data-col]` has a `.sort-btn`; the header's `aria-sort` flips between ascending and descending.

## How to get to it (user POV)

Open the page. Click a column header (Symbol) to sort; click again to reverse.

## Driving it with verify.py

- `verify.py compose holdings --json`.
- Pass means: 5 rows, "5 positions", total "$52,614.10", day P/L contains "$342.58", movers mention EXD, pill says "Weekend", Symbol sort puts `ex1` first then `ex5` first with matching `aria-sort`.
- Evidence: `evidence/holdings/sorted-desc.png`, `result.json`.

## Gotchas

- The default sort is Market value descending, so the first row before any click is EXC, not EXA.
- Money is formatted with `toLocaleString(undefined)`; the browser context is pinned to `en-US` so the strings are stable.
- On a weekday clock the app may try to fetch quotes; those requests are aborted and the journey still passes, but the pill text changes. Keep `fixed_time` on a weekend.
