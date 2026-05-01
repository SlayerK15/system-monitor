"""Flask entrypoint for the cross-platform Performance Monitor.

Run:  python app.py            # serves on http://127.0.0.1:8765
Or:   python app.py --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import argparse
import webbrowser
from threading import Timer

from flask import Flask, jsonify, send_from_directory

from system_monitor import SystemMonitor

app = Flask(__name__, static_folder="static", static_url_path="")
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


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Performance Monitor")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open the browser")
    args = parser.parse_args()

    url = f"http://{args.host if args.host != '0.0.0.0' else '127.0.0.1'}:{args.port}"
    print(f"Performance Monitor is running at {url}")
    if not args.no_browser:
        Timer(1.0, _open_browser, args=(url,)).start()
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
