"""Local preview with EXAMPLE holdings (made-up symbols and numbers, never real data).

Serves the repo root and, for `/` and `/index.html`, injects a script that seeds
localStorage with dev/example-holdings.json before the app boots. Add `?empty=1`
to see the empty state. Nothing is written to the repo.

    python3 dev/preview.py --port 8901 [--file index.html]
"""
import argparse, http.server, json, os, socketserver, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page(fname, empty):
    html = open(os.path.join(ROOT, fname), encoding="utf-8").read()
    if empty:
        seed = "localStorage.removeItem('stockHoldings_v1');"
    else:
        data = json.load(open(os.path.join(ROOT, "dev", "example-holdings.json"), encoding="utf-8"))
        seed = "localStorage.setItem('stockHoldings_v1', %s);" % json.dumps(json.dumps(data))
    tag = "<script>/* EXAMPLE data injected by dev/preview.py */%s</script>" % seed
    return html.replace("<head>", "<head>" + tag, 1).encode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8901)
    ap.add_argument("--file", default="index.html")
    ap.add_argument("--bind", default="127.0.0.1")
    a = ap.parse_args()

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *x, **k):
            super().__init__(*x, directory=ROOT, **k)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path in ("/", "/index.html"):
                body = page(a.file, "empty=1" in u.query)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return super().do_GET()

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((a.bind, a.port), H) as s:
        print("preview on http://%s:%d/ (EXAMPLE data)" % (a.bind, a.port), flush=True)
        s.serve_forever()


if __name__ == "__main__":
    main()
