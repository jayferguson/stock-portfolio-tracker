"""Proves crafted holdings can't inject markup into the page.

Loads index.html in headless Chrome and renders, in one run:
  1. a saved holding (localStorage) whose symbol and name are HTML/JS payloads;
  2. a crafted CSV pushed through the real import path, handleFile() -> XLSX -> parseImportedRows();
then shows a toast with the imported name and inspects the rendered DOM.

Fails (exit 1) if any payload element exists in the page, any payload handler ran,
or the payload text is not shown literally; prints `PASS: ...` when it holds. Needs
`pip install playwright`, Google Chrome or Chromium, and network access to the page's
CDNs (Tailwind, SheetJS). Quote APIs are blocked during the run. Without Playwright or
a browser the test is reported as skipped (unittest skipTest), never as a pass.

    python3 tests/check_no_markup_injection.py [path/to/index.html]
"""
import json, os, re, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.abspath(sys.argv.pop(1) if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
                       else os.path.join(ROOT, "index.html"))

SEED = [{
    "id": "crafted1",
    "symbol": "<img id=xss-sym src=x onerror=\"document.documentElement.dataset.pwned='symbol'\">",
    "name": "<b id=xss-name>bold</b><svg id=xss-svg onload=\"document.documentElement.dataset.pwned='name'\"></svg>",
    "shares": 3, "currentPrice": 10, "changePercent": 9,
}]

CSV = ('Symbol,Name,Shares,Price,Change %\n'
       '"<img id=xss-imp src=x onerror=alert(1)>","<i id=xss-impname>x</i><img src=y onerror=\\"document.documentElement.dataset.pwned=\'import\'\\">",5,10,20\n')

HARNESS = """
<script>
window.addEventListener('load', () => setTimeout(() => {
  window.alert = () => { document.documentElement.dataset.pwned = 'alert'; };
  const csv = %s;
  handleFile(new File([csv], 'crafted.csv', { type: 'text/csv' }));
  setTimeout(() => {
    // Keep the crafted saved holding next to the imported one so both render together.
    holdings = holdings.concat(%s);
    renderTable(); updateSummary();
    showToast('Imported ' + (holdings[0] && holdings[0].name));
    setTimeout(() => {
      const ids = ['xss-sym', 'xss-name', 'xss-svg', 'xss-imp', 'xss-impname'];
      const text = document.body.innerText;
      const result = {
        rows: document.querySelectorAll('#table-body tr').length,
        injected: ids.filter(id => document.getElementById(id)),
        stray: document.querySelectorAll('#table-body img, #table-body svg:not([aria-hidden]), #table-body b, #table-body i, #movers img, #toast-container img, #toast-container i').length,
        pwned: document.documentElement.dataset.pwned || null,
        literal: text.includes('<b id=xss-name>bold</b>') && text.includes('<i id=xss-impname>x</i>'),
      };
      const pre = document.createElement('pre');
      pre.id = 'xss-result';
      pre.textContent = 'XSSRESULT' + JSON.stringify(result) + 'XSSEND';
      document.body.appendChild(pre);
    }, 400);
  }, 1500);
}, 300));
</script>
"""


def launch(p):
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    try:
        return p.chromium.launch(executable_path=chrome, args=["--no-sandbox"]) if chrome else p.chromium.launch()
    except Exception as e:  # no browser available
        raise unittest.SkipTest("No Chrome or Chromium could be launched: %s" % str(e).splitlines()[0])


class NoMarkupInjection(unittest.TestCase):
    def test_crafted_saved_and_imported_holdings_render_as_text_only(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("Playwright is not installed: pip install playwright (uses your installed Chrome)")
        html = open(PAGE, encoding="utf-8").read()
        seed = "<script>localStorage.setItem('stockHoldings_v1', %s);</script>" % json.dumps(json.dumps(SEED))
        html = html.replace("<head>", "<head>" + seed, 1)
        html = html.replace("</body>", HARNESS % (json.dumps(CSV), json.dumps(SEED)) + "</body>", 1)
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            f = os.path.join(tmp, "index.html")
            open(f, "w", encoding="utf-8").write(html)
            b = launch(p)
            try:
                pg = b.new_page()
                # No live quote calls during the check
                pg.route(re.compile(r"(onclickmedia|finnhub)"), lambda route: route.abort())
                pg.goto("file://" + f)
                try:
                    pg.wait_for_selector("#xss-result", state="attached", timeout=30000)
                except Exception:
                    self.fail("harness did not finish (page error or CDN unreachable)")
                text = pg.locator("#xss-result").text_content()
            finally:
                b.close()
        r = json.loads(re.search(r"XSSRESULT(.*?)XSSEND", text, re.S).group(1))
        problems = []
        if r["rows"] < 2:
            problems.append("expected 2 rendered rows, got %d" % r["rows"])
        if r["injected"]:
            problems.append("payload elements in the DOM: %s" % ", ".join(r["injected"]))
        if r["stray"]:
            problems.append("%d stray payload tags in table/movers/toasts" % r["stray"])
        if r["pwned"]:
            problems.append("payload handler ran (%s)" % r["pwned"])
        if not r["literal"]:
            problems.append("payload text not shown literally")
        print(json.dumps(r))
        self.assertEqual(problems, [], "FAIL: " + "; ".join(problems))
        print("PASS: crafted saved and imported holdings render as text only")


if __name__ == "__main__":
    unittest.main()
