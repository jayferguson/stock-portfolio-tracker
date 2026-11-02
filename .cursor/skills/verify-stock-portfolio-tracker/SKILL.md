---
name: verify-stock-portfolio-tracker
description: "Drive and prove stock-portfolio-tracker (single static index.html, holdings in localStorage) in headless Chrome against the EXAMPLE seed from dev/preview.py. Use before claiming a tracker UI change works, when reviewing a tracker PR, or when an agent needs a checker-side gate verdict. Quote APIs are always blocked; nothing real is loaded."
---

# Verify stock-portfolio-tracker

A project-local control CLI for this repo (`stock-portfolio-tracker`). It launches an isolated preview server with made-up holdings, drives the page the way a user does (clicks, typing, keyboard shortcuts, dialogs), captures evidence, and gives a gate verdict. The engine is `verify.py`. Everything app-specific is data: `checks/app.toml` holds launch, doctor, browser policy and gate settings, `checks/scenarios/<feature>.toml` holds one user journey per mapped feature, and `checks/private_scan.toml` holds the public-repo leak patterns. When the app changes, edit the data, not the engine.

**Hard rules**

- EXAMPLE data only. Launch runs `dev/preview.py`, which injects `dev/example-holdings.json` (EXA…EXE). Never seed real holdings, and never put real names, account numbers, emails, keys, IPs or machine paths in this skill. **This repo is public.**
- Loopback only (`allow_remote = false`; port 8901 is refused because humans use it). The page may reach only loopback and its CDNs; `finnhub.io` and `api.onclickmedia.com` are always aborted.
- Don't edit product code from this skill. Only `.cursor/skills/verify-stock-portfolio-tracker/` changes; the gate's `scope_check` enforces it.
- Run `scan_diff.py` before every push. It is also a gate check.

## Launch

```bash
cd <stock-portfolio-tracker checkout>
python3 .cursor/skills/verify-stock-portfolio-tracker/verify.py launch --json    # --plan prints the command only; --port N pins a port
```

This starts `python3 dev/preview.py --port <free port> --bind 127.0.0.1` in its own process group and writes `scratch/instance.state` (pid, port, base_url) and `scratch/server.log`. Ready means `GET /` contains "EXAMPLE data injected". Running launch again while the instance is alive returns the same instance.

## Doctor

```bash
python3 .cursor/skills/verify-stock-portfolio-tracker/verify.py doctor --json
python3 .cursor/skills/verify-stock-portfolio-tracker/verify.py doctor --base-url http://127.0.0.1:PORT -j
```

Read-only GETs: `/` must carry the EXAMPLE injection, `stockHoldings_v1` and `#table-body`; `/?empty=1` must clear storage; `/dev/example-holdings.json` must be the EXAMPLE file. It also checks for a Playwright python (`VERIFY_PW_PYTHON`, else `~/.venvs/pw/bin/python`, else the current python) and Chrome (`/usr/bin/google-chrome` or chromium). Drive runs the same checks first and refuses an instance that fails them.

## Drive

```bash
python3 .cursor/skills/verify-stock-portfolio-tracker/verify.py features                  # list the map, check map/scenario consistency
python3 .cursor/skills/verify-stock-portfolio-tracker/verify.py drive holdings --json     # one journey
python3 .cursor/skills/verify-stock-portfolio-tracker/verify.py drive all --json          # all journeys
python3 .cursor/skills/verify-stock-portfolio-tracker/verify.py drive search --plan       # print steps, no browser
python3 .cursor/skills/verify-stock-portfolio-tracker/verify.py compose all --json        # launch -> doctor -> drive -> cleanup
```

Each journey gets a fresh browser profile (dark scheme, en-US, America/New_York, 1440x1000) with the clock fixed to Saturday 2026-10-31 12:00 ET. Any console error or page error fails the journey, except aborted-request noise.

| Feature | Journey (checks/scenarios/) | Proves |
|---|---|---|
| `holdings` | `holdings.toml` | 5 rows, "5 positions", total $52,614.10, day P/L $342.58, movers, weekend pill, Symbol sort asc/desc with `aria-sort` |
| `search` | `search.toml` | `/` focuses search; "gamma" → only EXC; Escape clears; no match → empty state |
| `add-holding` | `add-holding.toml` | Add stock dialog: EXZ 10 × $50 → 6 rows, $53,114.10, saved in `localStorage` |
| `edit-holding` | `edit-holding.toml` | Inline shares edit and Edit dialog update totals and storage; Escape cancels |
| `empty-state` | `empty-state.toml` | `/?empty=1` shows "No holdings yet"; Load sample data fills 5 rows |
| `api-settings` | `api-settings.toml` | Real-time prices dialog opens focused on the key field; Escape closes; nothing saved |

Step vocabulary (validated by the gate): `goto`, `wait`, `click`, `dblclick`, `fill`, `select`, `check`, `press`, `focus`, `viewport`, `eval`, `wait_ms`, `shot`, `expect_count`, `expect_text`, `expect_attr`, `expect_visible`, `expect_hidden`, `expect_eval`, `expect_http` (GET only). Every step may carry `why` and `timeout_ms`.

**Dry-run** is on by default. The app has no server-side state, so journeys write only to their own throwaway browser profile and to `evidence/`. A journey marked `writes = true` (none today) would be skipped on an instance the skill didn't launch unless you pass `--no-dry-run`.

## Evidence

`.cursor/skills/verify-stock-portfolio-tracker/evidence/<feature>/` holds `result.json` (every step with its observed detail, blocked requests, console), named screenshots, `final.png`, and `fail.png` on failure. `evidence/gate/result.json` holds the last gate verdict. `evidence/` and `scratch/` are gitignored, and the gate fails if either is tracked. Proof standard: the real user path (clicks, typing and keys, not JS setters), the action and the resulting state, and the `localStorage` side effect for edits.

## Cleanup

```bash
python3 .cursor/skills/verify-stock-portfolio-tracker/verify.py cleanup --json
```

Kills only the process group in `scratch/instance.state`, and only if its cmdline still contains `dev/preview.py`. It never kills by name. `evidence/` is kept; the output reports `evidence_present`.

## Gate (checker-side)

```bash
python3 .cursor/skills/verify-stock-portfolio-tracker/verify.py gate --json
python3 .cursor/skills/verify-stock-portfolio-tracker/verify.py gate --diff-base <ref> --allow-path 'index.html' --json   # reviewing a product PR
```

The gate reports `verdict`, `failed_check`, `suggestion` (what to fix first, naming the failing journey step and its screenshot), `checks` and `warnings`. It never fixes code. A false pass is worse than a false fail: a missing tool, a crashed launch, a repo check that prints SKIP instead of PASS, or a missing merge-base is a fail.

1. `tests`: `tests/check_no_markup_injection.py` and `tests/check_table_fits_desktop.py` (each must print `PASS`) and `tests/check_hover_glide.py` (unittest: must run at least one test and end in a bare `OK`; `OK (skipped=N)` is a fail), all under the Playwright python (they need network to the CDNs), then every journey on a fresh owned instance, which is always torn down.
2. `typecheck`: `compile()` on `dev/`, `tests/` and the skill's Python; `node --check` on the inline `<script>` blocks in `index.html`; the scenario schema (known steps and keys, at least one `expect_*` per journey, every `features/*.md` driven and linked from the README).
3. `lint`: n/a, because the repo configures no linter.
4. `private_scan`: `scan_diff.py` scans every line the branch adds (committed, working tree, untracked) against `checks/private_scan.toml`: emails (example.com allowed), IPv4 (loopback and documentation ranges allowed), `*.ts.net` hosts, token shapes, Finnhub key literals, absolute home-directory or scratch-workspace paths, 9+ digit runs, and data file types (`.csv`, `.xlsx`, `.env`...). A stricter pass adds regexes (real names, tickers) from a file **outside the repo**: `PRIVATE_PATTERNS_FILE` if set (it must exist), else the `extra_patterns_file` default in `checks/private_scan.toml`. If that default is missing (CI, other machines), the stricter pass is skipped and the gate lists a warning instead of failing. The output reports `extra_patterns_source` and the extra pattern count, never the patterns. `scan_diff.py --all` scans every tracked file.
5. `scope_check`: every change against `merge-base HEAD origin/main` must be under this skill dir or an `--allow-path` glob, and `evidence/` and `scratch/` must not be tracked. The gate also fails if running it dirtied the tree (`gate_side_effects`).

Red proofs (2026-11-02, a throwaway clone, deleted afterwards). (a) Dropping name matching from the search filter in `index.html` left both repo checks green, but the gate failed `tests` at `search` step 5 (`#table-body tr` count 0, expected 1, `evidence/search/fail.png`), and `scope_check` listed `index.html`. (b) Appending a made-up email and a private-range IP to a scenario comment failed `private_scan` with two redacted hits (`email`, `ipv4`); everything else stayed green. (c) Running the gate with a Playwright-less python made `check_hover_glide` print `OK (skipped=1)`, and the gate failed `tests`. (d) With the default extra-patterns file missing, `scan_diff.py` passed with a warning that the gate lists under `warnings`; with `PRIVATE_PATTERNS_FILE` set to a missing file it exited 2; with a planted made-up name and a matching extra pattern it reported one redacted `private-file#1` hit. Green on `main` dc4d093 plus this skill: all 5 checks passed, 3/3 repo checks, 6/6 journeys, 27 extra patterns, no warnings.

## Helpers

`verify.py --help` and `verify.py <cmd> --help` list every flag; all subcommands take `--json`/`-j`. `scan_diff.py --help` for the leak scan. The feature map is in `features/README.md`. Keep the map honest with `/maintain-verification-skill`.
