"""Flask server + native window launcher for the Performance Monitor.

By default the dashboard opens in a real desktop window using ``pywebview``
(Edge WebView2 on Windows, WKWebView on macOS, Qt WebEngine on Linux).
Pass ``--browser`` to fall back to the system browser, or ``--no-open`` to
just run the HTTP server.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from contextlib import closing

from flask import Flask, jsonify, send_from_directory

from .monitor import SystemMonitor

_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=_STATIC, static_url_path="")
monitor = SystemMonitor()


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/stats")
def stats():
    return jsonify(monitor.snapshot())


@app.route("/api/health")
def health():
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# server lifecycle helpers


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


def _serve(host: str, port: int) -> None:
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


# ---------------------------------------------------------------------------
# entrypoint


def main() -> None:
    parser = argparse.ArgumentParser(prog="system-monitor", description="Performance Monitor")
    parser.add_argument("--browser", action="store_true",
                        help="Open in the system browser instead of a native window.")
    parser.add_argument("--no-open", action="store_true",
                        help="Run the HTTP server only — don't open any UI.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1). Use 0.0.0.0 for LAN access.")
    parser.add_argument("--port", type=int, default=0,
                        help="TCP port (default: pick a free one).")
    args = parser.parse_args()

    port = args.port or _free_port()
    threading.Thread(target=_serve, args=(args.host, port), daemon=True).start()

    visible_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    url = f"http://{visible_host}:{port}"

    if not _wait_for_server(port):
        print(f"Performance Monitor: failed to start server on {url}", file=sys.stderr)
        sys.exit(1)

    print(f"Performance Monitor: {url}")

    if args.no_open:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    if args.browser:
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    # Native window mode (default).
    try:
        import webview  # type: ignore
    except ImportError:
        print(
            "pywebview is not installed; falling back to the system browser.\n"
            "Install with: uv sync   (or: uv pip install pywebview)",
            file=sys.stderr,
        )
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    # On Linux, force the Qt backend so PyQt6 wheels work without system GTK packages.
    gui = "qt" if sys.platform.startswith("linux") else None

    webview.create_window(
        "Performance Monitor",
        url,
        width=780,
        height=1020,
        min_size=(640, 720),
        resizable=True,
    )
    try:
        webview.start(gui=gui)
    except Exception as exc:  # pragma: no cover - depends on user environment
        print(f"Native window failed to start ({exc}); opening browser instead.", file=sys.stderr)
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
