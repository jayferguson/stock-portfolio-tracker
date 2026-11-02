#!/usr/bin/env python3
"""Agent-facing verification CLI for a browser-driven web app (data-driven).

Everything app-specific lives in checks/app.toml (how to launch, what "ready"
means, the gate's commands, URL policy) and checks/scenarios/*.toml (one file
per mapped feature: the user journey as a list of steps). This file is the
engine; edit the data, not the engine, when the app changes.

Subcommands: doctor, launch, drive, compose, features, gate, cleanup.
Every subcommand takes --json. Run `verify.py <cmd> --help` for flags.
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent
REPO = SKILL_DIR.parents[2]
CHECKS = SKILL_DIR / "checks"
SCENARIOS = CHECKS / "scenarios"
FEATURES = SKILL_DIR / "features"
SCRATCH = SKILL_DIR / "scratch"
EVIDENCE = SKILL_DIR / "evidence"
STATE = SCRATCH / "instance.state"
SKILL_REL = SKILL_DIR.relative_to(REPO).as_posix() + "/"

# The step vocabulary. Scenario files may use only these `do` values; the gate's
# typecheck rejects anything else, so a typo cannot silently skip a check.
STEP_KEYS: dict[str, tuple[set[str], set[str]]] = {
    # do: (required keys, optional keys)
    "goto": ({"path"}, {"query"}),
    "wait": ({"sel"}, {"state"}),
    "click": ({"sel"}, {"nth"}),
    "dblclick": ({"sel"}, {"nth"}),
    "fill": ({"sel", "value"}, {"nth"}),
    "select": ({"sel", "value"}, {"nth"}),
    "check": ({"sel"}, {"nth", "on"}),
    "press": ({"key"}, {"sel"}),
    "focus": ({"sel"}, {"nth"}),
    "viewport": ({"width", "height"}, set()),
    "eval": ({"js"}, set()),
    "wait_ms": ({"ms"}, set()),
    "shot": ({"name"}, {"full_page"}),
    "expect_count": ({"sel"}, {"min", "max", "eq"}),
    "expect_text": ({"sel"}, {"contains", "not_contains", "equals", "matches", "nth"}),
    "expect_attr": ({"sel", "attr"}, {"equals", "contains", "absent", "nth"}),
    "expect_visible": ({"sel"}, {"nth"}),
    "expect_hidden": ({"sel"}, {"nth"}),
    "expect_eval": ({"js"}, {"equals", "contains", "min", "max", "truthy"}),
    "expect_http": ({"path"}, {"status", "contains", "not_contains"}),
}
COMMON_STEP_KEYS = {"do", "why", "timeout_ms"}


# ---------------------------------------------------------------- utilities
def load_cfg() -> dict[str, Any]:
    with open(CHECKS / "app.toml", "rb") as f:
        return tomllib.load(f)


CFG = load_cfg()


def emit(obj: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, sort_keys=True, default=str))
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (list, dict)):
                v = json.dumps(v, default=str)
            print(f"{k}: {v}")
    else:
        print(obj)


def http_get(url: str, timeout: float = 8.0) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def free_port(host: str) -> int:
    refuse = set(CFG["launch"].get("refuse_ports", []))
    for _ in range(50):
        s = socket.socket()
        s.bind((host, 0))
        p = s.getsockname()[1]
        s.close()
        if p not in refuse:
            return p
    raise RuntimeError("no free port")


def port_in_use(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def read_state() -> dict[str, Any] | None:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pid_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return ""


def owned_instance() -> dict[str, Any] | None:
    """The instance this skill launched, if it is still alive and still ours."""
    st = read_state()
    if not st:
        return None
    if not pid_alive(st["pid"]) or st["marker"] not in pid_cmdline(st["pid"]):
        return None
    return st


def host_is_loopback(base_url: str) -> bool:
    h = urllib.parse.urlparse(base_url).hostname or ""
    return h in ("127.0.0.1", "localhost", "::1")


def expand(cmd: list[str], **extra: Any) -> list[str]:
    vals = {"python": sys.executable, "pw_python": browser_python() or "", "repo": str(REPO),
            "skill": str(SKILL_DIR), "scratch": str(SCRATCH), **{k: str(v) for k, v in extra.items()}}
    return [c.format(**vals) for c in cmd]


def browser_python() -> str | None:
    try:
        import playwright  # noqa: F401
        return sys.executable
    except ImportError:
        pass
    for c in [os.environ.get("VERIFY_PW_PYTHON", ""), *CFG["browser"].get("python_candidates", [])]:
        c = os.path.expanduser(c)
        if c and Path(c).exists():
            return c
    return None


def chrome_path() -> str | None:
    for c in CFG["browser"].get("chrome_candidates", []):
        p = shutil.which(c) or (c if Path(c).exists() else None)
        if p:
            return p
    return None


# ---------------------------------------------------------------- scenarios
def scenario_files() -> dict[str, Path]:
    return {p.stem: p for p in sorted(SCENARIOS.glob("*.toml"))}


def load_scenario(fid: str) -> dict[str, Any]:
    files = scenario_files()
    if fid not in files:
        raise SystemExit(f"unknown feature '{fid}'. Mapped: {', '.join(files)}")
    with open(files[fid], "rb") as f:
        sc = tomllib.load(f)
    sc.setdefault("id", fid)
    return sc


def validate_scenarios() -> list[str]:
    """Schema check for every scenario plus feature-map consistency. Returns problems."""
    problems: list[str] = []
    files = scenario_files()
    if not files:
        problems.append("no scenarios under checks/scenarios/")
    for fid, p in files.items():
        try:
            with open(p, "rb") as f:
                sc = tomllib.load(f)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{p.name}: TOML parse error: {e}")
            continue
        for k in ("title", "feature_doc", "steps"):
            if k not in sc:
                problems.append(f"{p.name}: missing top-level '{k}'")
        doc = sc.get("feature_doc")
        if doc and not (FEATURES / doc).exists():
            problems.append(f"{p.name}: feature_doc features/{doc} does not exist")
        steps = sc.get("steps", [])
        if not any(s.get("do", "").startswith("expect_") for s in steps):
            problems.append(f"{p.name}: no expect_* step, so it can never fail")
        for i, s in enumerate(steps):
            do = s.get("do")
            if do not in STEP_KEYS:
                problems.append(f"{p.name} step {i}: unknown do='{do}'")
                continue
            req, opt = STEP_KEYS[do]
            missing = req - set(s)
            extra = set(s) - req - opt - COMMON_STEP_KEYS
            if missing:
                problems.append(f"{p.name} step {i} ({do}): missing {sorted(missing)}")
            if extra:
                problems.append(f"{p.name} step {i} ({do}): unknown keys {sorted(extra)}")
            if do in ("expect_text",) and not ({"contains", "not_contains", "equals", "matches"} & set(s)):
                problems.append(f"{p.name} step {i} (expect_text): needs contains/not_contains/equals/matches")
            if do == "expect_count" and not ({"min", "max", "eq"} & set(s)):
                problems.append(f"{p.name} step {i} (expect_count): needs min/max/eq")
            if do == "expect_eval" and not ({"equals", "contains", "min", "max", "truthy"} & set(s)):
                problems.append(f"{p.name} step {i} (expect_eval): needs equals/contains/min/max/truthy")
    docs = {p.name for p in FEATURES.glob("*.md")} - {"README.md"}
    used = set()
    for p in files.values():
        try:
            with open(p, "rb") as f:
                used.add(tomllib.load(f).get("feature_doc"))
        except Exception:  # noqa: BLE001
            pass
    for d in sorted(docs - used):
        problems.append(f"features/{d} has no scenario in checks/scenarios/ (map lists a feature nothing drives)")
    readme = (FEATURES / "README.md").read_text() if (FEATURES / "README.md").exists() else ""
    for d in sorted(docs):
        if f"./{d}" not in readme:
            problems.append(f"features/README.md does not link ./{d}")
    return problems


class StepFailed(Exception):
    pass


def poll(fn, timeout_ms: int) -> Any:
    """Retry fn until it returns (ok, detail) with ok True, or the timeout passes."""
    end = time.time() + timeout_ms / 1000
    while True:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
        if ok:
            return detail
        if time.time() >= end:
            raise StepFailed(detail)
        time.sleep(0.1)


def run_step(page, s: dict[str, Any], base: str, outdir: Path, default_timeout: int) -> str:
    do = s["do"]
    t = int(s.get("timeout_ms", default_timeout))
    sel = s.get("sel")
    loc = page.locator(sel).nth(int(s.get("nth", 0))) if sel else None
    if do == "goto":
        url = base.rstrip("/") + s["path"] + (("?" + s["query"]) if s.get("query") else "")
        r = page.goto(url, wait_until="domcontentloaded", timeout=max(t, 30000))
        if r is None or r.status >= 400:
            raise StepFailed(f"GET {s['path']} -> {r.status if r else 'no response'}")
        return f"{r.status}"
    if do == "wait":
        page.wait_for_selector(sel, state=s.get("state", "visible"), timeout=t)
        return "ok"
    if do == "click":
        loc.click(timeout=t)
        return "clicked"
    if do == "dblclick":
        loc.dblclick(timeout=t)
        return "dblclicked"
    if do == "fill":
        loc.fill(str(s["value"]), timeout=t)
        return f"filled {s['value']!r}"
    if do == "select":
        loc.select_option(str(s["value"]), timeout=t)
        return f"selected {s['value']!r}"
    if do == "check":
        (loc.check if s.get("on", True) else loc.uncheck)(timeout=t)
        return "checked" if s.get("on", True) else "unchecked"
    if do == "press":
        if loc is not None:
            loc.press(s["key"], timeout=t)
        else:
            page.keyboard.press(s["key"])
        return f"pressed {s['key']}"
    if do == "focus":
        loc.focus(timeout=t)
        return "focused"
    if do == "viewport":
        page.set_viewport_size({"width": int(s["width"]), "height": int(s["height"])})
        return f"{s['width']}x{s['height']}"
    if do == "eval":
        return json.dumps(page.evaluate(s["js"]), default=str)[:300]
    if do == "wait_ms":
        page.wait_for_timeout(int(s["ms"]))
        return f"{s['ms']}ms"
    if do == "shot":
        p = outdir / f"{s['name']}.png"
        page.screenshot(path=str(p), full_page=bool(s.get("full_page", False)))
        return p.name

    if do == "expect_count":
        def f():
            n = page.locator(sel).count()
            ok = (("eq" not in s or n == s["eq"]) and ("min" not in s or n >= s["min"])
                  and ("max" not in s or n <= s["max"]))
            return ok, f"count({sel})={n}"
        return poll(f, t)
    if do == "expect_text":
        def f():
            txt = loc.inner_text(timeout=min(t, 2000))
            ok = True
            if "contains" in s:
                ok &= s["contains"] in txt
            if "not_contains" in s:
                ok &= s["not_contains"] not in txt
            if "equals" in s:
                ok &= txt.strip() == s["equals"]
            if "matches" in s:
                ok &= re.search(s["matches"], txt) is not None
            return ok, f"text({sel})={txt[:160]!r}"
        return poll(f, t)
    if do == "expect_attr":
        def f():
            v = loc.get_attribute(s["attr"], timeout=min(t, 2000))
            if s.get("absent"):
                return v is None, f"{s['attr']}={v!r}"
            ok = v is not None
            if "equals" in s:
                ok &= v == s["equals"]
            if "contains" in s:
                ok &= v is not None and s["contains"] in v
            return ok, f"{sel}[{s['attr']}]={v!r}"
        return poll(f, t)
    if do == "expect_visible":
        return poll(lambda: (loc.is_visible(), f"visible({sel})={loc.is_visible()}"), t)
    if do == "expect_hidden":
        return poll(lambda: (loc.is_hidden(), f"hidden({sel})={loc.is_hidden()}"), t)
    if do == "expect_eval":
        def f():
            v = page.evaluate(s["js"])
            ok = True
            if "equals" in s:
                ok &= v == s["equals"]
            if "contains" in s:
                ok &= isinstance(v, (str, list)) and s["contains"] in v
            if "min" in s:
                ok &= isinstance(v, (int, float)) and v >= s["min"]
            if "max" in s:
                ok &= isinstance(v, (int, float)) and v <= s["max"]
            if "truthy" in s:
                ok &= bool(v) == bool(s["truthy"])
            return ok, f"eval={json.dumps(v, default=str)[:200]}"
        return poll(f, t)
    if do == "expect_http":
        def f():
            code, body = http_get(base.rstrip("/") + s["path"])
            ok = code == int(s.get("status", 200))
            if "contains" in s:
                ok &= s["contains"] in body
            if "not_contains" in s:
                ok &= s["not_contains"] not in body
            return ok, f"GET {s['path']} -> {code} ({len(body)} bytes)"
        return poll(f, t)
    raise StepFailed(f"unknown step {do}")


def drive_features(fids: list[str], base: str, plan_only: bool, may_write: bool) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    scs = [load_scenario(f) for f in fids]
    if plan_only:
        return [{"feature": sc["id"], "title": sc["title"], "writes": sc.get("writes", False),
                 "steps": [{k: v for k, v in s.items()} for s in sc["steps"]]} for sc in scs]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [{"feature": f, "ok": False, "error": "playwright not importable (drive re-execs under "
                 "browser.python_candidates; none found)"} for f in fids]
    bcfg = CFG["browser"]
    chrome = chrome_path()
    allow = [re.compile(r) for r in bcfg.get("allow_url_regex", [])]
    block = [re.compile(r) for r in bcfg.get("block_url_regex", [])]
    console_allow = [re.compile(r) for r in bcfg.get("console_allow_regex", [])]
    with sync_playwright() as p:
        kw = {"args": ["--no-sandbox"], "headless": True}
        browser = p.chromium.launch(executable_path=chrome, **kw) if chrome else p.chromium.launch(**kw)
        for sc in scs:
            fid = sc["id"]
            outdir = EVIDENCE / fid
            if outdir.exists():
                shutil.rmtree(outdir)
            outdir.mkdir(parents=True)
            res: dict[str, Any] = {"feature": fid, "title": sc["title"], "base_url": base, "steps": [],
                                   "ok": True, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            if sc.get("writes") and not may_write:
                res.update(ok=None, skipped="scenario writes app state; refused on an instance this skill did "
                           "not launch (dry-run). Launch an owned instance or pass --no-dry-run on a synthetic one.")
                results.append(res)
                (outdir / "result.json").write_text(json.dumps(res, indent=2))
                continue
            vp = sc.get("viewport", bcfg.get("viewport", {"width": 1400, "height": 1000}))
            ctx = browser.new_context(viewport=vp, color_scheme=sc.get("color_scheme", bcfg.get("color_scheme", "light")),
                                      timezone_id=bcfg.get("timezone", "America/New_York"),
                                      locale=bcfg.get("locale", "en-US"))
            page = ctx.new_page()
            fixed = sc.get("fixed_time", bcfg.get("fixed_time"))
            if fixed:
                page.clock.set_fixed_time(fixed)
            console: list[dict[str, str]] = []
            blocked: list[str] = []

            def on_console(m, console=console):
                if m.type in ("error", "warning"):
                    console.append({"type": m.type, "text": m.text[:400]})

            page.on("console", on_console)
            page.on("pageerror", lambda e, console=console: console.append({"type": "pageerror", "text": str(e)[:400]}))

            def router(route, blocked=blocked):
                u = route.request.url
                if any(r.search(u) for r in block) or (allow and not any(r.search(u) for r in allow)):
                    blocked.append(u[:200])
                    return route.abort()
                return route.continue_()

            page.route("**/*", router)
            dt = int(sc.get("timeout_ms", bcfg.get("step_timeout_ms", 8000)))
            for i, s in enumerate(sc["steps"]):
                t0 = time.time()
                rec = {"i": i, "do": s["do"], **{k: s[k] for k in ("sel", "path", "why") if k in s}}
                try:
                    rec["detail"] = run_step(page, s, base, outdir, dt)
                    rec["ok"] = True
                except Exception as e:  # noqa: BLE001
                    rec["ok"] = False
                    rec["detail"] = f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"
                    res["ok"] = False
                    res["failed_step"] = i
                    try:
                        page.screenshot(path=str(outdir / "fail.png"), full_page=True)
                    except Exception:  # noqa: BLE001
                        pass
                rec["ms"] = int((time.time() - t0) * 1000)
                res["steps"].append(rec)
                if not rec["ok"]:
                    break
            if res["ok"]:
                page.screenshot(path=str(outdir / "final.png"), full_page=False)
            bad = [c for c in console if c["type"] in ("error", "pageerror")
                   and not any(r.search(c["text"]) for r in console_allow)]
            res["console"] = console
            res["blocked_requests"] = sorted(set(blocked))
            if bad and bcfg.get("fail_on_console_error", True):
                res["ok"] = False
                res["console_errors"] = bad
            ctx.close()
            res["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            (outdir / "result.json").write_text(json.dumps(res, indent=2))
            results.append(res)
        browser.close()
    return results


# ---------------------------------------------------------------- commands
def cmd_launch(args: argparse.Namespace) -> int:
    lc = CFG["launch"]
    host = lc.get("host", "127.0.0.1")
    st = owned_instance()
    if st:
        emit({"ok": True, "already_running": True, **st}, args.json)
        return 0
    port = args.port or free_port(host)
    if port in lc.get("refuse_ports", []):
        emit({"ok": False, "error": f"port {port} is refused by checks/app.toml (live/default app port)"}, args.json)
        return 2
    if port_in_use(host, port):
        emit({"ok": False, "error": f"{host}:{port} already in use; refusing to double-drive"}, args.json)
        return 2
    cmd = expand(lc["cmd"], port=port, host=host)
    plan = {"cmd": cmd, "cwd": str(REPO), "port": port}
    if args.plan:
        emit({"ok": True, "plan": plan}, args.json)
        return 0
    SCRATCH.mkdir(parents=True, exist_ok=True)
    log = open(SCRATCH / "server.log", "wb")
    env = {k: v for k, v in os.environ.items() if not any(k.startswith(p) for p in lc.get("scrub_env_prefixes", []))}
    proc = subprocess.Popen(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=env)
    base = f"http://{host}:{port}"
    st = {"pid": proc.pid, "port": port, "base_url": base, "marker": lc["marker"], "cmd": cmd,
          "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    STATE.write_text(json.dumps(st, indent=2))
    deadline = time.time() + float(lc.get("ready_timeout_s", 30))
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        code, body = http_get(base + lc["ready_path"], timeout=2)
        if code == 200 and all(m in body for m in lc.get("ready_contains", [])):
            ready = True
            break
        time.sleep(0.25)
    if not ready:
        tail = (SCRATCH / "server.log").read_text(errors="replace")[-1500:]
        _kill(st)
        emit({"ok": False, "error": "not ready before timeout (or exited); killed", "log_tail": tail}, args.json)
        return 1
    emit({"ok": True, **st}, args.json)
    return 0


def _kill(st: dict[str, Any]) -> str:
    pid = st["pid"]
    if not pid_alive(pid):
        res = "not running"
    elif st["marker"] not in pid_cmdline(pid):
        res = f"pid {pid} is not ours (cmdline lacks marker); left alone"
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            os.kill(pid, signal.SIGTERM)
        for _ in range(40):
            if not pid_alive(pid):
                break
            time.sleep(0.1)
        if pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        res = f"killed pid {pid}"
    try:
        os.waitpid(pid, os.WNOHANG)
    except OSError:
        pass
    STATE.unlink(missing_ok=True)
    return res


def cmd_cleanup(args: argparse.Namespace) -> int:
    st = read_state()
    out: dict[str, Any] = {"ok": True, "evidence_dir": str(EVIDENCE), "evidence_kept": True}
    out["instance"] = _kill(st) if st else "no instance recorded"
    for extra in CFG["launch"].get("cleanup_globs", []):
        for p in glob.glob(str(SCRATCH / extra)):
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.unlink(p)
    out["evidence_present"] = EVIDENCE.exists() and any(EVIDENCE.iterdir())
    emit(out, args.json)
    return 0


def resolve_base(args: argparse.Namespace) -> tuple[str | None, bool, str]:
    """(base_url, owned, why) — refuses bases the config forbids."""
    if getattr(args, "base_url", None):
        base = args.base_url
        if not host_is_loopback(base) and not CFG["launch"].get("allow_remote", False):
            return None, False, f"refused: {base} is not loopback; checks/app.toml allow_remote=false"
        st = owned_instance()
        return base, bool(st and st["base_url"].rstrip("/") == base.rstrip("/")), "explicit"
    st = owned_instance()
    if st:
        return st["base_url"], True, "owned instance from scratch/instance.state"
    return None, False, "no owned instance; run `verify.py launch` first or pass --base-url"


def doctor_checks(base: str) -> list[dict[str, Any]]:
    out = []
    for c in CFG["doctor"]["checks"]:
        code, body = http_get(base.rstrip("/") + c["path"])
        ok = code == int(c.get("status", 200)) and all(m in body for m in c.get("contains", []))
        out.append({"path": c["path"], "status": code, "ok": ok, "expect": c.get("contains", []),
                    "why": c.get("why", "")})
    return out


def cmd_doctor(args: argparse.Namespace) -> int:
    base, owned, why = resolve_base(args)
    if not base:
        emit({"ok": False, "error": why}, args.json)
        return 2
    checks = doctor_checks(base)
    tools = {"browser_python": browser_python(), "chrome": chrome_path()}
    ok = all(c["ok"] for c in checks) and all(tools.values())
    emit({"ok": ok, "base_url": base, "owned": owned, "checks": checks, "tools": tools}, args.json)
    return 0 if ok else 1


def _maybe_reexec_for_browser(argv: list[str]) -> None:
    try:
        import playwright  # noqa: F401
        return
    except ImportError:
        pass
    py = browser_python()
    if py and os.path.abspath(py) != os.path.abspath(sys.executable) and not os.environ.get("VERIFY_REEXEC"):
        os.environ["VERIFY_REEXEC"] = "1"
        os.execv(py, [py, str(Path(__file__).resolve()), *argv])


def cmd_drive(args: argparse.Namespace) -> int:
    fids = list(scenario_files()) if args.feature == "all" else [args.feature]
    if args.plan:
        emit({"ok": True, "plan": drive_features(fids, "", True, False)}, args.json)
        return 0
    base, owned, why = resolve_base(args)
    if not base:
        emit({"ok": False, "error": why}, args.json)
        return 2
    guard = doctor_checks(base)
    if not all(c["ok"] for c in guard):
        emit({"ok": False, "error": "doctor failed; refusing to drive", "checks": guard}, args.json)
        return 1
    may_write = owned or (args.no_dry_run and host_is_loopback(base))
    res = drive_features(fids, base, False, may_write)
    ok = all(r.get("ok") is True for r in res)
    summary = [{"feature": r["feature"], "ok": r.get("ok"), "failed_step": r.get("failed_step"),
                "skipped": r.get("skipped"), "console_errors": r.get("console_errors"), "error": r.get("error"),
                "failed_detail": (r["steps"][r["failed_step"]]["detail"] if r.get("failed_step") is not None else None),
                "evidence": str(EVIDENCE / r["feature"])} for r in res]
    emit({"ok": ok, "base_url": base, "owned": owned, "dry_run": not args.no_dry_run, "results": summary}
         if not args.verbose else {"ok": ok, "results": res}, args.json)
    return 0 if ok else 1


def cmd_compose(args: argparse.Namespace) -> int:
    ns = argparse.Namespace(json=True, port=None, plan=False)
    out: dict[str, Any] = {}
    buf = _capture(cmd_launch, ns)
    out["launch"] = buf
    rc = 1
    try:
        if buf[0] == 0:
            st = owned_instance()
            dns = argparse.Namespace(json=True, base_url=st["base_url"] if st else None)
            out["doctor"] = _capture(cmd_doctor, dns)
            fids = list(scenario_files()) if args.feature == "all" else [args.feature]
            res = drive_features(fids, st["base_url"], False, True) if st else []
            out["drive"] = [{"feature": r["feature"], "ok": r.get("ok"), "failed_step": r.get("failed_step"),
                             "console_errors": r.get("console_errors")} for r in res]
            rc = 0 if res and all(r.get("ok") is True for r in res) else 1
    finally:
        out["cleanup"] = _capture(cmd_cleanup, argparse.Namespace(json=True))
    out["ok"] = rc == 0
    out["evidence_dir"] = str(EVIDENCE)
    emit(out, args.json)
    return rc


def _capture(fn, ns) -> tuple[int, Any]:
    import contextlib
    import io
    b = io.StringIO()
    with contextlib.redirect_stdout(b):
        rc = fn(ns)
    try:
        return rc, json.loads(b.getvalue())
    except ValueError:
        return rc, b.getvalue()[-2000:]


def cmd_features(args: argparse.Namespace) -> int:
    rows = []
    for fid, p in scenario_files().items():
        with open(p, "rb") as f:
            sc = tomllib.load(f)
        rows.append({"feature": fid, "title": sc.get("title"), "doc": f"features/{sc.get('feature_doc')}",
                     "steps": len(sc.get("steps", [])), "writes": sc.get("writes", False)})
    problems = validate_scenarios()
    emit({"ok": not problems, "features": rows, "problems": problems}, args.json)
    return 0 if not problems else 1


# ---------------------------------------------------------------- gate
def run_cmd(c: dict[str, Any]) -> dict[str, Any]:
    cmd = expand(c["cmd"])
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=int(c.get("timeout_s", 600)))
        rc, out = p.returncode, (p.stdout + p.stderr)
    except FileNotFoundError as e:
        rc, out = 127, str(e)
    except subprocess.TimeoutExpired:
        rc, out = 124, "timeout"
    ok = rc == 0 and all(re.search(m, out) for m in c.get("must_match", []))
    return {"name": c["name"], "ok": ok, "rc": rc, "secs": round(time.time() - t0, 1),
            "tail": out.strip()[-800:] if not ok or c.get("show_tail") else out.strip()[-200:]}


def py_syntax(globs: list[str]) -> dict[str, Any]:
    files = sorted({f for g in globs for f in glob.glob(str(REPO / g), recursive=True)})
    files.append(str(Path(__file__).resolve()))
    bad = []
    for f in files:
        try:
            compile(Path(f).read_text(encoding="utf-8"), f, "exec")
        except SyntaxError as e:
            bad.append(f"{Path(f).relative_to(REPO)}:{e.lineno}: {e.msg}")
    return {"name": "py_syntax", "ok": not bad and bool(files), "files": len(files), "errors": bad}


def js_inline_syntax(pages: list[str]) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        return {"name": "js_inline_syntax", "ok": False, "error": "node not found (a missing checker is a fail)"}
    out_dir = SCRATCH / "js"
    out_dir.mkdir(parents=True, exist_ok=True)
    errs, n = [], 0
    for pg in pages:
        html = (REPO / pg).read_text(encoding="utf-8")
        for i, m in enumerate(re.finditer(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", html, re.S | re.I)):
            attrs, body = m.group(1), m.group(2)
            if "type=" in attrs and "module" not in attrs and "javascript" not in attrs:
                continue
            n += 1
            f = out_dir / f"{Path(pg).stem}.{i}.js"
            f.write_text(body)
            p = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
            if p.returncode:
                errs.append(f"{pg} <script #{i}>: {p.stderr.strip().splitlines()[-1] if p.stderr.strip() else 'error'}")
    return {"name": "js_inline_syntax", "ok": not errs and n > 0, "scripts": n, "errors": errs}


def git(*a: str) -> tuple[int, str]:
    p = subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True)
    return p.returncode, p.stdout.strip() + (("\n" + p.stderr.strip()) if p.returncode else "")


def scope_check(diff_base: str | None, allow: list[str]) -> dict[str, Any]:
    if diff_base:
        base = diff_base
    else:
        rc, base = git("merge-base", "HEAD", CFG["gate"].get("main_ref", "origin/main"))
        if rc:
            return {"name": "scope_check", "ok": False, "error": f"no merge-base with main: {base}"}
    rc1, changed = git("diff", "--name-only", base)
    rc2, untracked = git("ls-files", "--others", "--exclude-standard")
    if rc1 or rc2:
        return {"name": "scope_check", "ok": False, "error": changed or untracked}
    paths = sorted({p for p in (changed.splitlines() + untracked.splitlines()) if p})
    allowed = [SKILL_REL + "*", *CFG["gate"].get("scope_allow", []), *allow]
    out = [p for p in paths if not any(fnmatch.fnmatch(p, a) for a in allowed)]
    rc3, tracked = git("ls-files", SKILL_REL + "evidence", SKILL_REL + "scratch")
    leaked = [p for p in tracked.splitlines() if p]
    return {"name": "scope_check", "ok": not out and not leaked, "base": base[:12], "changed": len(paths),
            "out_of_scope": out, "tracked_evidence_or_scratch": leaked}


def cmd_gate(args: argparse.Namespace) -> int:
    g = CFG["gate"]
    _, status_before = git("status", "--porcelain", "--untracked-files=all")
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []

    # 1. tests: the repo's own tests, then every mapped UI journey on a fresh owned instance
    tests = [run_cmd(c) for c in g.get("tests", [])]
    if owned_instance():
        _kill(read_state())
        warnings.append("a previous owned instance was still running; stopped it before the gate")
    lrc, lout = _capture(cmd_launch, argparse.Namespace(json=True, port=None, plan=False))
    drives: list[dict[str, Any]] = []
    try:
        if lrc == 0:
            st = owned_instance()
            doc = doctor_checks(st["base_url"])
            if all(c["ok"] for c in doc):
                drives = drive_features(list(scenario_files()), st["base_url"], False, True)
            else:
                drives = [{"feature": "doctor", "ok": False, "error": doc}]
        else:
            drives = [{"feature": "launch", "ok": False, "error": lout}]
    finally:
        cl = _kill(read_state()) if read_state() else "nothing to stop"
    ui = {"name": "ui_journeys", "ok": bool(drives) and all(d.get("ok") is True for d in drives),
          "features": [{"feature": d["feature"], "ok": d.get("ok"), "failed_step": d.get("failed_step"),
                        "step": (d["steps"][d["failed_step"]] if d.get("failed_step") is not None else None),
                        "console_errors": d.get("console_errors"), "error": d.get("error")} for d in drives],
          "cleanup": cl}
    tests.append(ui)
    checks.append({"check": "tests", "ok": all(t["ok"] for t in tests), "parts": tests})

    # 2. typecheck: syntax of product + skill code, and the scenario schema / feature-map consistency
    tc = [py_syntax(g.get("py_globs", []))]
    if g.get("inline_js_pages"):
        tc.append(js_inline_syntax(g["inline_js_pages"]))
    probs = validate_scenarios()
    tc.append({"name": "scenario_schema", "ok": not probs, "problems": probs})
    tc += [run_cmd(c) for c in g.get("typecheck", [])]
    checks.append({"check": "typecheck", "ok": all(t["ok"] for t in tc), "parts": tc})

    # 3. lint
    if g.get("lint"):
        li = [run_cmd(c) for c in g["lint"]]
        checks.append({"check": "lint", "ok": all(x["ok"] for x in li), "parts": li})
    else:
        checks.append({"check": "lint", "ok": True, "na": g.get("lint_na", "no linter configured")})

    # 4. private-data scan (when the repo has one)
    if g.get("private_scan"):
        ps = [run_cmd(c) for c in g["private_scan"]]
        checks.append({"check": "private_scan", "ok": all(x["ok"] for x in ps), "parts": ps})

    # 5. scope
    sc = scope_check(args.diff_base, args.allow_path or [])
    _, status_after = git("status", "--porcelain", "--untracked-files=all")
    side = sorted(set(status_after.splitlines()) - set(status_before.splitlines()))
    sc["gate_side_effects"] = side
    if side:
        sc["ok"] = False
    checks.append({"check": "scope_check", **{k: v for k, v in sc.items() if k != "name"}})

    failed = next((c["check"] for c in checks if not c["ok"]), None)
    hints = g.get("suggestions", {})
    verdict = {"verdict": "pass" if failed is None else "fail", "failed_check": failed,
               "suggestion": hints.get(failed, "") if failed else "", "checks": checks, "warnings": warnings,
               "evidence_dir": str(EVIDENCE)}
    if failed == "tests":
        bad = [t for t in tests if not t["ok"]]
        if bad and bad[0]["name"] == "ui_journeys":
            f0 = next(f for f in ui["features"] if not f["ok"])
            verdict["suggestion"] += (f" First failing journey: {f0['feature']} step {f0['failed_step']} "
                                      f"({(f0.get('step') or {}).get('detail') or f0.get('console_errors') or f0.get('error')}); "
                                      f"see evidence/{f0['feature']}/fail.png.")
        elif bad:
            verdict["suggestion"] += f" First failing: {bad[0]['name']}."
    (EVIDENCE / "gate").mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "gate" / "result.json").write_text(json.dumps(verdict, indent=2, default=str))
    if args.json:
        emit(verdict, True)
    else:
        print(f"verdict: {verdict['verdict']}" + (f" (failed: {failed})" if failed else ""))
        for c in checks:
            print(f"  {'PASS' if c['ok'] else 'FAIL'}  {c['check']}" + (f"  [n/a: {c['na']}]" if c.get("na") else ""))
        if verdict["suggestion"]:
            print(f"fix first: {verdict['suggestion']}")
    return 0 if failed is None else 1


# ---------------------------------------------------------------- cli
EPILOG = """\
typical loop (from the repo root):
  verify.py launch                 start an isolated instance on a free loopback port
  verify.py doctor                 is it worth driving? (read-only)
  verify.py drive <feature|all>    run mapped journeys in headless Chrome; evidence/<feature>/
  verify.py cleanup                stop only what launch started; evidence is kept
  verify.py compose <feature|all>  launch -> doctor -> drive -> cleanup in one go
  verify.py gate --json            checker verdict: tests, typecheck, lint, [private_scan], scope_check
  verify.py features               list mapped features and check map/scenario consistency

dry-run: on by default. Drives write only to the instance this skill launched (a
throwaway store) and to evidence/. A scenario marked writes=true is skipped on an
instance the skill did not launch unless --no-dry-run (loopback only). Data: checks/app.toml
and checks/scenarios/*.toml; edit those, not this file, when the app changes.
"""


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", "-j", action="store_true", help="machine-readable output on stdout")
    ap = argparse.ArgumentParser(prog="verify.py", description=__doc__.split("\n\n")[0] + f" App: {CFG['app']['name']}.",
                                 epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("launch", parents=[common], help="start an isolated instance (synthetic data, free loopback port)")
    sp.add_argument("--port", type=int, help="pin a port (refused if in use or listed in refuse_ports)")
    sp.add_argument("--plan", action="store_true", help="print the launch command without starting anything")
    sp.set_defaults(fn=cmd_launch)
    sp = sub.add_parser("doctor", parents=[common], help="read-only: is the instance up, synthetic, and drivable?")
    sp.add_argument("--base-url", help="instance to check (default: the one launch started)")
    sp.set_defaults(fn=cmd_doctor)
    sp = sub.add_parser("drive", parents=[common], help="run one mapped journey (or all) in headless Chrome",
                        epilog="features: " + ", ".join(scenario_files()))
    sp.add_argument("feature", help="feature id (file stem under checks/scenarios/) or 'all'")
    sp.add_argument("--base-url", help="drive this instance instead of the owned one (loopback only unless allowed)")
    sp.add_argument("--dry-run", action="store_true", default=True, help="default: writes only to an owned instance")
    sp.add_argument("--no-dry-run", action="store_true", help="allow writes=true journeys on a non-owned loopback instance")
    sp.add_argument("--plan", action="store_true", help="print the journey steps without opening a browser")
    sp.add_argument("--verbose", "-v", action="store_true", help="full per-step records in the output")
    sp.set_defaults(fn=cmd_drive)
    sp = sub.add_parser("compose", parents=[common], help="launch -> doctor -> drive -> cleanup")
    sp.add_argument("feature", help="feature id or 'all'")
    sp.set_defaults(fn=cmd_compose)
    sp = sub.add_parser("features", parents=[common], help="list mapped features; check scenario/map consistency")
    sp.set_defaults(fn=cmd_features)
    sp = sub.add_parser("gate", parents=[common], help="checker verdict; never fixes code",
                        description="Runs tests (repo tests + every UI journey on a fresh owned instance), typecheck "
                        "(syntax + scenario schema), lint, private_scan (if configured), then scope_check (every change "
                        "vs merge-base with main must sit in the skill dir or an --allow-path). Reports verdict, "
                        "failed_check and what to fix first. A false pass is worse than a false fail: a missing tool "
                        "or crashed launch is a fail.")
    sp.add_argument("--diff-base", help="git ref for scope_check (default: merge-base HEAD origin/main)")
    sp.add_argument("--allow-path", action="append", help="extra glob allowed by scope_check (e.g. a product PR's files)")
    sp.set_defaults(fn=cmd_gate)
    sp = sub.add_parser("cleanup", parents=[common], help="stop only the instance launch started; keep evidence/")
    sp.set_defaults(fn=cmd_cleanup)
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(argv)
    if args.cmd in ("drive", "compose", "gate") and not getattr(args, "plan", False):
        _maybe_reexec_for_browser(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
