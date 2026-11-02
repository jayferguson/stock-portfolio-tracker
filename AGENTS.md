# Agent rules — stock-portfolio-tracker

Self-contained stock portfolio tracker that runs entirely in the browser: one `index.html`, no server and no build step. Tailwind and SheetJS load from CDNs; holdings persist in `localStorage` (`stockHoldings_v1`). Automatic price refresh runs only in regular US market hours (9:30–16:00 ET, weekdays); manual refresh always works. `README.md` is the user reference.

**This repo is public.** Never commit real holdings, API keys, hostnames, IP addresses, emails or local paths. Use the made-up data in `dev/example-holdings.json`.

## Layout

- `index.html`: the whole app (markup, styles, script).
- `dev/preview.py`: local preview server that seeds the EXAMPLE holdings.
- `dev/example-holdings.json`: made-up symbols and numbers.
- `tests/check_no_markup_injection.py`, `tests/check_table_fits_desktop.py`: headless-Chrome checks.

## Run locally

Open `index.html` in a browser, or serve it with example data:

```text
python3 dev/preview.py --port 8901
```

Add `?empty=1` to the URL for the empty state. The preview writes nothing to the repo.

## Tests

Each check is a standalone script that exits 0 and prints `PASS: ...`, or exits 1:

```text
python3 tests/check_no_markup_injection.py
python3 tests/check_table_fits_desktop.py
```

They need a Python with `playwright` installed, Google Chrome or Chromium, and network access to the CDNs (quote APIs are blocked during the run). There is no CI; run both before handing off a change to `index.html`.

## Conventions

- Anything from saved holdings, imports or quote APIs is rendered as text, never as markup (the injection check enforces this).
- The holdings table must fit its card at 1024 px and up, and the page must not scroll sideways on a phone (320 px).
- Keep it a single file with no build step.

## Git

Changes go through a pull request; do not push to `main` directly.

## Verify

A `verify-stock-portfolio-tracker` skill is being added by the Verify bot under `.cursor/skills/` (pending; not in the repo yet). Once it lands, prove every change with it before calling the work done.
