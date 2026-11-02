# Search

The toolbar search box filters the holdings table by symbol or name as you type.

## Sub-features

- `shortcut`: pressing `/` while focus is on the page focuses `#search-input`.
- `filter`: case-insensitive match on symbol or name; rows re-render on each `input` event.
- `clear`: Escape inside the box clears it and restores all rows.
- `no match`: zero rows shows `#empty-state`.

## How to get to it (user POV)

Press `/` (or click the search box) → type "gamma" → one row; press Escape → all rows.

## Driving it with verify.py

- `verify.py compose search --json`.
- Pass means: `/` focuses the box, "gamma" leaves only `ex3`, "exb" leaves one row, Escape empties the box and shows 5 rows, a nonsense query shows 0 rows and the empty state.
- Evidence: `evidence/search/filtered.png`, `result.json`.

## Gotchas

- The `/` shortcut is ignored while an input has focus; the journey presses it right after load, when the body has focus.
- The empty state shown for "no matches" is the same element as the empty-portfolio view, with the same "No holdings yet" copy.
