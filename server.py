#!/usr/bin/env python
"""Lokální prohlížeč STEP souborů.

Spustí malý server na 127.0.0.1, který umí procházet adresáře se STEP
soubory, převádět je na vyžádání a otevřít nativní dialog pro výběr
souboru kdekoli na disku.

    ~/.venvs/cad/bin/python server.py ~/cesta/k/projektu

Bez argumentu bere aktuální adresář. Výsledky převodu se kešují v cache/
podle času poslední změny zdroje, takže druhé otevření je okamžité.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
VIEWER = os.path.join(HERE, "viewer")
CACHE = os.path.join(HERE, "cache")

ROOTS: list[str] = []
PICKED: set[str] = set()      # cesty, které uživatel sám vybral v dialogu


def is_allowed(path: str) -> bool:
    """Server smí otevřít jen soubory pod zadanými kořeny nebo ručně vybrané."""
    path = os.path.abspath(path)
    if path in PICKED:
        return True
    return any(
        os.path.commonpath([path, root]) == root
        for root in ROOTS
        if os.path.exists(path)
    )


def cache_path(path: str) -> str:
    stamp = f"{os.path.abspath(path)}:{os.path.getmtime(path)}"
    key = hashlib.sha1(stamp.encode()).hexdigest()[:16]
    return os.path.join(CACHE, f"{key}.json")


def build_model(path: str) -> dict:
    cached = cache_path(path)
    if os.path.exists(cached):
        with open(cached, encoding="utf-8") as fh:
            return json.load(fh)

    import stepkit                      # až tady, ať start serveru není pomalý
    data = stepkit.to_viewer_json(path)
    data["path"] = os.path.abspath(path)
    os.makedirs(CACHE, exist_ok=True)
    with open(cached, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    return data


def list_files() -> list[dict]:
    import stepkit
    out = []
    for root in ROOTS:
        for rel in stepkit.find_step_files(root):
            full = os.path.join(root, rel)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            out.append({
                "root": os.path.basename(root) or root,
                "rel": rel.replace(os.sep, "/"),
                "path": full,
                "kb": round(size / 1024),
            })
    return out


def native_pick() -> str | None:
    """Otevře systémový dialog pro výběr souboru. Vrací cestu, nebo None."""
    if sys.platform != "darwin":
        return None
    script = (
        'tell application "System Events" to activate\n'
        'set f to choose file with prompt "Vyber STEP soubor"\n'
        'POSIX path of f'
    )
    try:
        done = subprocess.run(["osascript", "-e", script],
                              capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if done.returncode != 0:
        return None                    # uživatel dal Zrušit
    path = done.stdout.strip()
    return path or None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=VIEWER, **kwargs)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write("  %s\n" % (fmt % args))

    def guess_type(self, path):
        kind = super().guess_type(path)
        if kind in ("text/html", "application/json", "text/plain"):
            return kind + "; charset=utf-8"
        return kind

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route == "/api/ping":
            return self.send_json({"server": True,
                                   "roots": [os.path.basename(r) or r for r in ROOTS],
                                   "native": sys.platform == "darwin"})

        if route == "/api/files":
            try:
                return self.send_json(list_files())
            except Exception as exc:
                return self.send_json({"error": str(exc)}, 500)

        if route == "/api/pick":
            path = native_pick()
            if not path:
                return self.send_json({"cancelled": True})
            if not path.endswith(("step", "stp", "STEP", "STP")):
                return self.send_json({"error": "To není STEP soubor."}, 400)
            PICKED.add(os.path.abspath(path))
            return self.send_json({"path": path, "name": os.path.basename(path)})

        if route == "/api/model":
            path = (query.get("path") or [""])[0]
            if not path or not os.path.isfile(path):
                return self.send_json({"error": "Soubor neexistuje."}, 404)
            if not is_allowed(path):
                return self.send_json({"error": "Mimo povolené adresáře."}, 403)
            try:
                return self.send_json(build_model(path))
            except Exception as exc:
                return self.send_json({"error": f"Převod selhal: {exc}"}, 500)

        return super().do_GET()


def main() -> int:
    ap = argparse.ArgumentParser(description="Lokální prohlížeč STEP souborů")
    ap.add_argument("roots", nargs="*", default=None,
                    help="adresáře se STEP soubory (výchozí: aktuální)")
    # 8787 bývá obsazený jinou aplikací, proto začínáme výš.
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    for root in (args.roots or [os.getcwd()]):
        full = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(full):
            print(f"přeskakuji, není adresář: {full}", file=sys.stderr)
            continue
        ROOTS.append(full)
    if not ROOTS:
        print("žádný platný adresář", file=sys.stderr)
        return 1

    # Na obsazeném portu zkusíme pár následujících, ať to nepadá kvůli cizí aplikaci.
    httpd = None
    for port in range(args.port, args.port + 10):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            print(f"  port {port} je obsazený, zkouším další", file=sys.stderr)
    if httpd is None:
        print("nenašel jsem volný port", file=sys.stderr)
        return 1

    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print("Prohlížeč STEP")
    for root in ROOTS:
        print(f"  kořen: {root}")
    print(f"  běží na {url}   (Ctrl+C ukončí)")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nkonec")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
