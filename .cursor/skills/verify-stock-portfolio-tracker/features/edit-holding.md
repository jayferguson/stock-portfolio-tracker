# Edit holding

Holdings can be edited inline in the table (shares, price, change %) or through the per-row Edit dialog. Totals recompute live and storage updates on each change.

## Sub-features

- `inline`: `tr[data-id=exN] input[data-field=shares|currentPrice|changePercent]`, labelled e.g. "Shares of EXD".
- `dialog`: `button[aria-label='Edit EXB']` opens `#modal` titled "Edit holding", prefilled from the row.
- `cancel`: Escape closes the dialog without saving.

## How to get to it (user POV)

Type a new number into a row's Shares box, or click the pencil on a row → change Price → Save.

## Driving it with verify.py

- `verify.py compose edit-holding --json`.
- Pass means: EXD shares 12 → 22 gives "$54,297.60" and storage `ex4.shares == 22`; EXB price → 100 via the dialog gives "$52,935.40" and storage `ex2.currentPrice == 100`; still 5 rows; Escape closes the EXC dialog.
- Evidence: `evidence/edit-holding/edited.png`, `result.json`.

## Gotchas

- Totals depend on step order: the dialog edit's expected total includes the earlier inline edit.
- `fill` fires `input`; the app recomputes on input, so no blur is needed.
