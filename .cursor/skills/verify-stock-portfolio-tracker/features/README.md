# stock-portfolio-tracker verification map

The maintained source for proving the tracker's user-facing behavior: the single static page `index.html`, which keeps holdings in browser `localStorage` (`stockHoldings_v1`). Read this index first, then the feature file you need.

## Baseline preconditions

- Always drive an **isolated EXAMPLE instance**: `verify.py launch` runs `dev/preview.py` on a free loopback port. It serves the repo root and injects `dev/example-holdings.json` (EXA…EXE, made-up names and numbers) into `localStorage` before the app boots, on every load of `/`. `/?empty=1` clears storage instead.
- Each journey gets a fresh browser profile, so storage never leaks between journeys or into a human's browser.
- The clock is fixed to Saturday 2026-10-31 12:00 ET, so the market pill reads "Weekend • Updates paused" and the app does not auto-fetch quotes.
- Quote APIs (`finnhub.io`, `api.onclickmedia.com`) are always aborted. Only loopback and the page's CDNs (Tailwind, SheetJS on jsDelivr, Google Fonts) are allowed; anything else is aborted and logged in `result.json` (`blocked_requests`).

## Driving conventions

- Run from the repo root. Feature ids are the file stems under `checks/scenarios/`; each scenario is a TOML list of steps (`goto`, `click`, `fill`, `press`, `expect_*`, `shot`...). Edit the scenario, not `verify.py`, when the UI changes.
- `verify.py drive <id>` (or `all`) runs headless Chrome via Playwright (`VERIFY_PW_PYTHON`, else `~/.venvs/pw/bin/python`, else the current python). A console error or page error fails the journey; only aborted-request noise is allowed.
- Prefer ids, `data-id`/`data-col`/`data-field` attributes and `aria-*` labels over text and coordinates.
- Expected money values are computed from the seed file. If `dev/example-holdings.json` changes, recompute them (the `why` on each step shows the arithmetic).

## Proof and skip reporting

- A pass means every step ran and every `expect_*` held. Evidence: `evidence/<id>/result.json`, named screenshots, `final.png`, and `fail.png` on failure.
- The app has no server-side state; the side effect of an edit is `localStorage.stockHoldings_v1`, checked with `expect_eval`, not just the DOM.
- A journey that cannot run reports failed or skipped with the reason. Never mark a skip as verified.

## Feature entry contract

Each feature file has an H1 and a paragraph, then exactly four H2s: `Sub-features`, `How to get to it (user POV)`, `Driving it with verify.py`, `Gotchas`.

## Features

- [Holdings table](./holdings.md) — EXAMPLE rows, totals, day P/L, movers, market pill, sort by symbol.
- [Search](./search.md) — `/` shortcut, filter by symbol or name, Escape clears, no-match empty state.
- [Add holding](./add-holding.md) — Add stock dialog; new row, totals and storage update.
- [Edit holding](./edit-holding.md) — inline shares edit and the Edit dialog; Escape cancels.
- [Empty state](./empty-state.md) — empty portfolio view and Load sample data.
- [API settings](./api-settings.md) — Real-time prices dialog opens focused and closes without saving.

## Not yet mapped

Excel import/export (needs fixture `.xlsx` files and download capture), Refresh prices against stubbed quote APIs (needs `page.route` fulfilment, not just abort), Clear all data (confirm dialog), sorting by the other columns, mobile layout. Add a scenario plus a feature file per item; the gate's `scenario_schema` check fails if a feature file has no scenario.
