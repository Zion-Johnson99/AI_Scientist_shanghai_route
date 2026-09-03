"""Serve the published local product over 127.0.0.1 with no external access."""

from __future__ import annotations

import argparse
import functools
import http.server
import socket
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent
PRODUCT_ROOT: Path = RUN_ROOT / "publish" / "local-product"
DEFAULT_PORT: int = 8765
PROBE_PATHS: tuple[str, ...] = ("/index.html", "/styles.css", "/app.js", "/map.js")


class OfflineHandler(http.server.SimpleHTTPRequestHandler):
    """Static handler bound to 127.0.0.1 that logs one line per request."""

    def log_message(self, format: str, *args: object) -> None:
        sys.stdout.write("[serve] " + (format % args) + "\n")
        sys.stdout.flush()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


def free_port(preferred: int) -> int:
    """Return the preferred port if free, otherwise an ephemeral one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as spare:
        spare.bind(("127.0.0.1", 0))
        return int(spare.getsockname()[1])


def probe(port: int) -> dict[str, int]:
    """Fetch the core assets once and return their status codes."""
    codes: dict[str, int] = {}
    for path in PROBE_PATHS:
        url = f"http://127.0.0.1:{port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                codes[path] = int(response.status)
        except OSError:
            codes[path] = 0
    return codes


def serve(port: int, open_browser: bool, background: bool) -> int:
    """Start the server; return a process exit code."""
    if not (PRODUCT_ROOT / "index.html").is_file():
        sys.stdout.write(f"[serve] 缺少 {PRODUCT_ROOT / 'index.html'}\n")
        return 1
    handler = functools.partial(OfflineHandler, directory=str(PRODUCT_ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/index.html"
    sys.stdout.write(f"[serve] {url}\n")
    sys.stdout.flush()
    if background:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        codes = probe(port)
        sys.stdout.write(f"[serve] probe={codes}\n")
        server.shutdown()
        return 0 if all(code == 200 for code in codes.values()) else 1
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main() -> int:
    """Parse arguments and serve."""
    parser = argparse.ArgumentParser(description="Serve the run-local web product.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    port = free_port(args.port)
    return serve(port, not args.no_browser, args.probe_only)


if __name__ == "__main__":
    raise SystemExit(main())
