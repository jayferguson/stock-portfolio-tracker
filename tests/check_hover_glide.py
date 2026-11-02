"""Browser check: the gliding hover highlight follows the pointer in the holdings table and the action bar,
keeps the normal keyboard focus ring, and is off under prefers-reduced-motion (plain hover fills instead).

Loads index.html in headless Chrome with dev/example-holdings.json (EXAMPLE data). Quote APIs are blocked.
Tests are skipped (never passed) when Playwright or a browser is missing.

    python3 tests/check_hover_glide.py [path/to/index.html]
"""
import json, os, re, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.abspath(sys.argv.pop(1) if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
                       else os.path.join(ROOT, "index.html"))

GLIDE = """(sel) => {
  const g = document.querySelector(sel + ' > .glide');
  if (!g) return null;
  const r = g.getBoundingClientRect(), cs = getComputedStyle(g);
  return { x: r.x, y: r.y, w: r.width, h: r.height, opacity: parseFloat(cs.opacity), display: cs.display };
}"""


def close(a, b, tol=1.5):
    return abs(a - b) <= tol


class HoverGlide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("Playwright is not installed: pip install playwright")
        with open(os.path.join(ROOT, "dev", "example-holdings.json"), encoding="utf-8") as f:
            data = json.load(f)
        seed = "<script>localStorage.setItem('stockHoldings_v1', %s);</script>" % json.dumps(json.dumps(data))
        with open(PAGE, encoding="utf-8") as f:
            html = f.read().replace("<head>", "<head>" + seed, 1)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.file = os.path.join(cls.tmp.name, "index.html")
        with open(cls.file, "w", encoding="utf-8") as f:
            f.write(html)
        cls.pw = sync_playwright().start()
        chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
        try:
            cls.browser = (cls.pw.chromium.launch(executable_path=chrome, args=["--no-sandbox"]) if chrome
                           else cls.pw.chromium.launch())
        except Exception as e:  # no browser available
            cls.pw.stop()
            raise unittest.SkipTest("No Chrome or Chromium could be launched: %s" % str(e).splitlines()[0])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()

    def open(self, reduced=False):
        pg = self.browser.new_page(viewport={"width": 1280, "height": 900},
                                   reduced_motion="reduce" if reduced else "no-preference")
        pg.route(re.compile(r"(onclickmedia|finnhub)"), lambda route: route.abort())
        pg.goto("file://" + self.file)
        pg.wait_for_selector("#table-body tr", timeout=30000)
        pg.wait_for_timeout(500)
        self.addCleanup(pg.close)
        return pg

    def hover(self, pg, el, dx=None):
        b = el.bounding_box()
        pg.mouse.move(b["x"] + (dx if dx is not None else b["width"] / 2), b["y"] + b["height"] / 2)
        pg.wait_for_timeout(450)  # longer than the moderate tier (160ms)
        return b

    def assert_on(self, g, b, what):
        self.assertIsNotNone(g, "no .glide highlight in the %s" % what)
        self.assertGreater(g["opacity"], 0.9, "%s highlight is not lit" % what)
        for k, gk in (("x", "x"), ("y", "y"), ("width", "w"), ("height", "h")):
            self.assertTrue(close(g[gk], b[k]), "%s highlight %s=%.1f, item %s=%.1f" % (what, gk, g[gk], k, b[k]))

    def test_table_highlight_follows_rows(self):
        pg = self.open()
        rows = pg.query_selector_all("#table-body tr")
        self.assertGreaterEqual(len(rows), 3)
        for row in rows[:3]:
            b = self.hover(pg, row, dx=300)
            g = pg.evaluate(GLIDE, ".table-scroll")
            self.assert_on(g, b, "table")
        pg.mouse.move(5, 5)
        pg.wait_for_timeout(300)
        self.assertLess(pg.evaluate(GLIDE, ".table-scroll")["opacity"], 0.1, "table highlight stays lit after leaving")

    def test_action_bar_highlight_follows_buttons_and_keeps_focus_ring(self):
        pg = self.open()
        btns = pg.query_selector_all(".action-bar [data-glide]")
        labels = [b.inner_text().strip() for b in btns]
        self.assertEqual(labels, ["Import Excel", "Export", "Refresh prices", "API settings"])
        for btn in btns:
            b = self.hover(pg, btn)
            self.assert_on(pg.evaluate(GLIDE, ".action-bar"), b, "action bar (%s)" % btn.inner_text().strip())
        # In the gap between two buttons the highlight stays on the last one
        b1, b2 = btns[0].bounding_box(), btns[1].bounding_box()
        pg.mouse.move((b1["x"] + b1["width"] + b2["x"]) / 2, b1["y"] + b1["height"] / 2)
        pg.wait_for_timeout(300)
        g = pg.evaluate(GLIDE, ".action-bar")
        self.assertGreater(g["opacity"], 0.9, "highlight goes dark in the gap between buttons")
        # Keyboard focus shows the normal ring while the pointer highlight is lit elsewhere
        pg.focus(".action-bar [data-glide]:nth-of-type(1)")
        pg.keyboard.press("Tab")
        ring = pg.evaluate("""() => { const a = document.activeElement, cs = getComputedStyle(a);
            return { visible: a.matches(':focus-visible'), style: cs.outlineStyle, width: parseFloat(cs.outlineWidth),
                     glide: a.classList.contains('glide') }; }""")
        self.assertTrue(ring["visible"] and ring["style"] != "none" and ring["width"] >= 2,
                        "keyboard focus ring missing: %r" % ring)
        self.assertGreater(pg.evaluate(GLIDE, ".action-bar")["opacity"], 0.9, "focus moved or hid the pointer highlight")
        # Pointer onto the search field: highlight goes out
        self.hover(pg, pg.query_selector(".action-bar input"))
        self.assertLess(pg.evaluate(GLIDE, ".action-bar")["opacity"], 0.1, "highlight stays lit over the search field")

    def test_off_under_reduced_motion(self):
        pg = self.open(reduced=True)
        row = pg.query_selector_all("#table-body tr")[1]
        self.hover(pg, row, dx=300)
        g = pg.evaluate(GLIDE, ".table-scroll")
        self.assertIsNotNone(g, "no .glide element in the table to switch off")
        self.assertEqual(g["display"], "none", "table highlight still shown under reduced motion")
        fill = pg.evaluate("(r) => getComputedStyle(r.querySelector('td')).backgroundColor", row)
        self.assertNotEqual(fill, "rgba(0, 0, 0, 0)", "no plain hover fill on the row under reduced motion")
        btn = pg.query_selector(".action-bar [data-glide]")
        self.hover(pg, btn)
        g = pg.evaluate(GLIDE, ".action-bar")
        self.assertIsNotNone(g, "no .glide element in the action bar to switch off")
        self.assertEqual(g["display"], "none", "action bar highlight still shown under reduced motion")
        self.assertEqual(pg.evaluate("(b) => getComputedStyle(b).backgroundColor", btn), "rgb(63, 63, 70)",
                         "no plain hover fill on the button under reduced motion")


if __name__ == "__main__":
    unittest.main(verbosity=2)
