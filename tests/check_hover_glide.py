"""Browser check: the gliding hover highlight follows the pointer in the holdings table and the action bar,
keeps the normal keyboard focus ring, and is off under prefers-reduced-motion (plain hover fills instead).
It is re-placed when the layout moves under a still pointer (table redraw or resize, action-bar wrap, a label
changing width), and plain CSS hover fills show whenever the glide script is not running.

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

    def open(self, reduced=False, init=None):
        pg = self.browser.new_page(viewport={"width": 1280, "height": 900},
                                   reduced_motion="reduce" if reduced else "no-preference")
        self.errors = []
        pg.on("pageerror", lambda e: self.errors.append(str(e)))
        if init:
            pg.add_init_script(init)
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

    # ---- the highlight follows layout changes without the pointer moving
    def settle(self, pg):
        pg.wait_for_timeout(300)  # one frame for the observers, then past the moderate tier

    def test_table_resize_re_places_the_highlight_on_the_row_still_under_the_pointer(self):
        pg = self.open()
        row = pg.query_selector_all("#table-body tr")[1]
        self.hover(pg, row, dx=30)   # over the first cell, which is still the element under the pointer after the resize
        before = pg.evaluate(GLIDE, ".table-scroll")
        under = "() => document.elementFromPoint(%d, %d)" % (row.bounding_box()["x"] + 30, row.bounding_box()["y"] + 20)
        cell = pg.evaluate_handle(under)
        pg.set_viewport_size({"width": 1100, "height": 900})        # the rows get narrower; the pointer stays put
        self.settle(pg)
        b = row.bounding_box()
        self.assertLess(b["width"], before["w"] - 50, "the resize did not change the row width")
        self.assertTrue(pg.evaluate("([c, f]) => c === f", [cell, pg.evaluate_handle(under)]),
                        "the pointer should still be over the same cell (no new pointerover)")
        self.assert_on(pg.evaluate(GLIDE, ".table-scroll"), b, "table after a resize")
        self.assertEqual(self.errors, [])

    def test_table_redraw_that_removes_the_row_under_the_pointer_turns_the_highlight_off(self):
        pg = self.open()
        rows = pg.query_selector_all("#table-body tr")
        self.hover(pg, rows[3], dx=300)
        first = rows[0].query_selector("td").inner_text().strip().split()[0]
        pg.fill("#search-input", first)                               # redraws the table; no pointer move
        self.settle(pg)
        self.assertEqual(pg.locator("#table-body tr").count(), 1)
        self.assertLess(pg.evaluate(GLIDE, ".table-scroll")["opacity"], 0.1,
                        "highlight still lit where the hovered row was")

    def test_table_redraw_keeps_the_highlight_on_the_row_now_under_the_pointer(self):
        pg = self.open()
        self.hover(pg, pg.query_selector_all("#table-body tr")[1], dx=300)
        pg.evaluate("sortBy('symbol')")                               # a full redraw: new <tr> elements
        self.settle(pg)
        row = pg.query_selector_all("#table-body tr")[1]
        self.assert_on(pg.evaluate(GLIDE, ".table-scroll"), row.bounding_box(), "table after a redraw")
        self.assertEqual(pg.get_attribute("#table-body", "data-fluid-hover-active-index"), "1")

    def test_action_bar_wrap_re_places_the_highlight(self):
        pg = self.open()
        api = pg.query_selector(".action-bar [data-glide]:nth-of-type(4)")
        self.assertEqual(api.inner_text().strip(), "API settings")
        b0 = self.hover(pg, api, dx=6)
        bar = pg.query_selector(".action-bar").bounding_box()
        # Narrow the bar so "API settings" wraps onto a second line; the pointer is left over the bar's own background
        pg.evaluate("(w) => document.querySelector('.action-bar').style.width = w + 'px'", b0["x"] + b0["width"] - bar["x"] - 4)
        self.settle(pg)
        b1 = api.bounding_box()
        self.assertGreater(b1["y"], b0["y"] + 20, "the button did not wrap")
        under = pg.evaluate("([x, y]) => { const e = document.elementFromPoint(x, y); return e && e.className; }",
                            [b0["x"] + 6, b0["y"] + b0["height"] / 2])
        self.assertIn("action-bar", under or "", "pointer should be over the bar's background after the wrap")
        self.assert_on(pg.evaluate(GLIDE, ".action-bar"), b1, "action bar after a wrap")
        self.assertEqual(self.errors, [])

    def test_highlight_goes_out_when_a_wrap_leaves_the_pointer_outside_the_bar(self):
        pg = self.open()
        api = pg.query_selector(".action-bar [data-glide]:nth-of-type(4)")
        b0 = self.hover(pg, api, dx=api.bounding_box()["width"] - 4)
        bar = pg.query_selector(".action-bar").bounding_box()
        pg.evaluate("(w) => document.querySelector('.action-bar').style.width = w + 'px'", b0["x"] + b0["width"] - bar["x"] - 12)
        self.settle(pg)
        right = pg.query_selector(".action-bar").bounding_box()
        self.assertGreater(b0["x"] + b0["width"] - 4, right["x"] + right["width"], "pointer should be outside the bar now")
        self.assertLess(pg.evaluate(GLIDE, ".action-bar")["opacity"], 0.1, "highlight lit though the pointer left the bar")

    def test_a_label_that_changes_width_re_sizes_the_highlight(self):
        pg = self.open()
        btn = pg.query_selector("#refresh-btn")
        b0 = self.hover(pg, btn, dx=10)
        pg.evaluate("document.querySelector('#refresh-btn span').textContent = 'Refreshing all prices now'")
        self.settle(pg)
        b1 = btn.bounding_box()
        self.assertGreater(b1["width"], b0["width"] + 30)
        self.assert_on(pg.evaluate(GLIDE, ".action-bar"), b1, "action bar after a label change")

    # ---- plain CSS hover fills whenever the glide is not running
    FAIL_GLIDE = """(() => { const add = EventTarget.prototype.addEventListener;
      EventTarget.prototype.addEventListener = function (type, ...rest) {
        if (type === 'pointerover') throw new Error('glide script failed (simulated)');
        return add.call(this, type, ...rest); }; })();"""

    def fills(self, pg):
        row = pg.query_selector_all("#table-body tr")[1]
        self.hover(pg, row, dx=300)
        td = pg.evaluate("(r) => getComputedStyle(r.querySelector('td')).backgroundColor", row)
        btn = pg.query_selector(".action-bar [data-glide]")
        rest = pg.evaluate("(b) => getComputedStyle(b).backgroundColor", btn)
        self.hover(pg, btn)
        return td, rest, pg.evaluate("(b) => getComputedStyle(b).backgroundColor", btn)

    def test_hover_fills_show_when_the_glide_script_fails(self):
        pg = self.open(init=self.FAIL_GLIDE)
        self.assertGreaterEqual(pg.locator("#table-body tr").count(), 3, "the app itself must still run")
        self.assertTrue(self.errors and all("simulated" in e for e in self.errors), self.errors)
        self.assertEqual(pg.locator(".glide-live").count(), 0)
        td, rest, hover = self.fills(pg)
        self.assertNotEqual(td, "rgba(0, 0, 0, 0)", "no hover fill on the row without the glide")
        self.assertEqual(hover, "rgb(63, 63, 70)", "no hover fill on the button without the glide")
        self.assertNotEqual(hover, rest)
        self.assertEqual(pg.evaluate(GLIDE, ".table-scroll")["opacity"], 0)

    def test_fills_step_aside_only_once_the_glide_runs(self):
        pg = self.open()
        self.assertEqual(pg.locator(".table-scroll.glide-live, .action-bar.glide-live").count(), 2)
        td, rest, hover = self.fills(pg)
        self.assertEqual(td, "rgba(0, 0, 0, 0)", "row fill doubles up with the glide")
        self.assertEqual(hover, rest, "button fill changes under the glide overlay")
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
