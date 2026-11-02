# API settings

The "API settings" toolbar button opens the "Real-time prices" dialog (`#api-modal`) for an optional Finnhub key; `#data-source-label` shows which quote source is active.

## Sub-features

- `open`: the dialog shows, titled "Real-time prices", with focus on `#finnhub-token`.
- `close`: Escape (or the close button / backdrop) hides it without saving.
- `save/remove key`: not driven; it would store a key in `localStorage.finnhubToken`.

## How to get to it (user POV)

Toolbar → API settings → read → Escape.

## Driving it with verify.py

- `verify.py compose api-settings --json`.
- Pass means: the dialog opens focused on the key field, Escape hides it, and no key is saved.
- Evidence: `evidence/api-settings/api-dialog.png`, `result.json`.

## Gotchas

- Never put a real Finnhub key in a scenario; this repo is public and `scan_diff.py` blocks key-shaped literals. Quote requests are aborted anyway.
