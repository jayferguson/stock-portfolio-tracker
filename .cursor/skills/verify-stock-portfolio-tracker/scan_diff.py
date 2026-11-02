#!/usr/bin/env python3
"""Scan what this branch ADDS for private data before pushing to the public repo.

Scans added lines in `git diff <base>` (committed + working tree) and every
untracked, non-ignored file, against checks/private_scan.toml plus an optional
PRIVATE_PATTERNS_FILE (one regex per line, kept outside the repo). Prints file
counts and redacted hits; exit 1 on any hit. Never prints a full matched value.
The extra file defaults to `extra_patterns_file` in checks/private_scan.toml;
when that default is missing the stricter pass is skipped with a warning.

    python3 .cursor/skills/verify-stock-portfolio-tracker/scan_diff.py [--base REF] [--all] [--json]
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

SKILL = Path(__file__).resolve().parent
REPO = SKILL.parents[2]
CFG_PATH = SKILL / "checks" / "private_scan.toml"
SELF_EXCLUDE = {CFG_PATH.relative_to(REPO).as_posix()}


def git(*a: str) -> str:
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True, check=True).stdout


def redact(s: str) -> str:
    return s[:3] + "…" + f"({len(s)} chars)" if len(s) > 6 else "…"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", help="git ref (default: merge-base HEAD origin/main)")
    ap.add_argument("--all", action="store_true", help="scan every tracked file, not just what the branch adds")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    cfg = tomllib.loads(CFG_PATH.read_text())
    pats = [(p["name"], re.compile(p["regex"]), [re.compile(x) for x in p.get("allow", [])]) for p in cfg["pattern"]]
    warnings: list[str] = []
    env_extra = os.environ.get("PRIVATE_PATTERNS_FILE")
    extra = None
    if env_extra:  # explicit: a missing file is an error, not a skip
        extra = Path(env_extra).expanduser()
        if not extra.is_file():
            print(f"scan_diff: PRIVATE_PATTERNS_FILE is set but not a file", file=sys.stderr)
            return 2
    elif cfg.get("extra_patterns_file"):
        p = Path(cfg["extra_patterns_file"]).expanduser()
        if p.is_file():
            extra = p
        else:
            warnings.append("extra patterns file (config default) not found; stricter pass skipped")
    n_extra = 0
    if extra:
        for i, line in enumerate(extra.read_text().splitlines()):
            if line.strip() and not line.startswith("#"):
                pats.append((f"private-file#{i + 1}", re.compile(line.strip(), re.I), []))
                n_extra += 1
    base = a.base or git("merge-base", "HEAD", "origin/main").strip()
    added: dict[str, list[tuple[int, str]]] = {}
    if a.all:
        for f in git("ls-files").splitlines():
            p = REPO / f
            if p.is_file():
                added[f] = list(enumerate(p.read_text(errors="replace").splitlines(), 1))
    else:
        cur, ln = None, 0
        for line in git("diff", "-U0", "--no-color", base).splitlines():
            if line.startswith("+++ "):
                cur = line[6:] if line.startswith("+++ b/") else None
                if cur:
                    added.setdefault(cur, [])
            elif line.startswith("@@"):
                m = re.search(r"\+(\d+)", line)
                ln = int(m.group(1)) if m else 0
            elif line.startswith("+") and cur:
                added[cur].append((ln, line[1:]))
                ln += 1
        for f in git("ls-files", "--others", "--exclude-standard").splitlines():
            p = REPO / f
            if p.is_file():
                added[f] = list(enumerate(p.read_text(errors="replace").splitlines(), 1))
    hits, files, lines = [], 0, 0
    for f, rows in sorted(added.items()):
        files += 1
        if any(fnmatch.fnmatch(f, g) for g in cfg.get("block_file_globs", [])) and not any(
                fnmatch.fnmatch(f, g) for g in cfg.get("allow_file_globs", [])):
            hits.append({"file": f, "line": 0, "pattern": "blocked-file-type", "match": Path(f).suffix})
        if f in SELF_EXCLUDE:
            continue
        for ln, text in rows:
            lines += 1
            for name, rx, allow in pats:
                for m in rx.finditer(text):
                    v = m.group(0)
                    if any(x.search(v) for x in allow):
                        continue
                    hits.append({"file": f, "line": ln, "pattern": name, "match": redact(v)})
    out = {"ok": not hits, "base": base[:12], "mode": "all-tracked" if a.all else "branch-adds",
           "files_scanned": files, "lines_scanned": lines, "patterns": [p[0] for p in pats],
           "extra_patterns_file": bool(extra),
           "extra_patterns_source": "env" if env_extra else ("config" if extra else None),
           "extra_patterns": n_extra, "warnings": warnings, "hits": hits}
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"scan_diff: {'clean' if not hits else 'HITS'} — {files} files, {lines} lines, {len(pats)} patterns"
              f" ({n_extra} from the extra file)")
        for w in warnings:
            print(f"  warning: {w}")
        for h in hits:
            print(f"  {h['file']}:{h['line']}: {h['pattern']} {h['match']}")
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(main())
