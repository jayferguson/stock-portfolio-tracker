"""Proves the holdings table fits its card on desktop and scrolls only inside its box on phones.

Loads index.html in headless Chrome with dev/example-holdings.json (EXAMPLE data) and checks:
  - at 1920, 1280 and 1024 px the table box has no horizontal scroll;
  - at 320 px the page itself never scrolls sideways (the table box may);
  - sort-header focus rings stay inside their header cell (not clipped by the box).
Exit 1 on any failure. Needs `pip install playwright`, Chrome or Chromium, and network
access to the page's CDNs. Quote APIs are blocked during the run.

    python3 tests/check_table_fits_desktop.py [path/to/index.html]
"""
import json, os, re, shutil, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESKTOP = (1920, 1280, 1024)

MEASURE = """() => {
  const box = document.querySelector('.table-scroll');
  if (!box) return { missing: true };
  const btns = [...document.querySelectorAll('thead .sort-btn')];
  const ring = btns.map(b => {
    const o = parseFloat(getComputedStyle(b, null).outlineOffset) || 0;
    const r = b.getBoundingClientRect(), th = b.closest('th').getBoundingClientRect();
    return r.top - o - 2 >= th.top - 0.5 && r.bottom + o + 2 <= th.bottom + 0.5;
  });
  return { page: document.documentElement.scrollWidth, box: box.clientWidth, table: box.scrollWidth,
           rows: document.querySelectorAll('#table-body tr').length, ringsInside: ring.every(Boolean) };
}"""


def main():
    page = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "index.html"))
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: pip install playwright (uses your installed Chrome)")
        return 0
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    data = json.load(open(os.path.join(ROOT, "dev", "example-holdings.json"), encoding="utf-8"))
    seed = "<script>localStorage.setItem('stockHoldings_v1', %s);</script>" % json.dumps(json.dumps(data))
    html = open(page, encoding="utf-8").read().replace("<head>", "<head>" + seed, 1)
    problems, seen = [], {}
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        f = os.path.join(tmp, "index.html")
        open(f, "w", encoding="utf-8").write(html)
        b = p.chromium.launch(executable_path=chrome, args=["--no-sandbox"]) if chrome else p.chromium.launch()
        for w in DESKTOP + (320,):
            pg = b.new_page(viewport={"width": w, "height": 900})
            pg.route(re.compile(r"(onclickmedia|finnhub)"), lambda route: route.abort())
            pg.goto("file://" + f)
            pg.wait_for_selector("#table-body tr", timeout=30000)
            pg.wait_for_timeout(800)
            m = seen[w] = pg.evaluate(MEASURE)
            pg.close()
            if m.get("missing"):
                problems.append("%dpx: no .table-scroll box around the holdings table" % w)
                continue
            if m["rows"] < 1:
                problems.append("%dpx: no rows rendered" % w)
            if m["page"] > w:
                problems.append("%dpx: page scrolls sideways (%dpx wide)" % (w, m["page"]))
            if w in DESKTOP and m["table"] > m["box"]:
                problems.append("%dpx: table %dpx is wider than its %dpx box" % (w, m["table"], m["box"]))
            if w in DESKTOP and not m["ringsInside"]:
                problems.append("%dpx: a sort-header focus ring spills out of its header cell" % w)
        b.close()
    print(json.dumps(seen))
    if problems:
        print("FAIL: " + "; ".join(problems))
        return 1
    print("PASS: table fits its box at %s px; page never scrolls sideways at 320 px" % ", ".join(map(str, DESKTOP)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
