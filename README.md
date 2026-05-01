# Performance Monitor

A cross-platform system monitor with a clean, modern dashboard. Runs as a
**standalone native window** on **Windows 10/11**, **macOS**, and **any Linux
distribution**.

![dashboard](docs/preview.png)

## What it shows

- **CPU** — utilization gauge, clock speed, thread count, temperature, 60-second history
- **GPU** — utilization, clock, VRAM, temperature, 60-second history (NVIDIA via `nvidia-smi`; Apple Silicon via `system_profiler`)
- **Memory** — usage bar, configured speed, slot population, committed memory
- **Storage** — per-disk usage, model, real-time read/write throughput, temperature, SMART health
- **Network** — connected SSID, download/upload throughput, IP address, ping latency, Wi-Fi signal strength
- **Power** — battery level, power source, time remaining, active power plan, voltage
- **Fans** — RPM and percent of every detected fan
- **System** — OS, motherboard, uptime, refresh time
- **SMART status** — overall health, reallocated sectors, power-on hours, drive temperature
- **Footer** — overall health, total uptime, lifetime data read / written, activity indicator

Sensors that aren't available on your platform gracefully degrade to "—"
rather than crashing the dashboard.

## Quick start

This project uses [**uv**](https://docs.astral.sh/uv/) for dependency
management. Install it once:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then launch the standalone window:

```bash
# macOS / Linux
./run.sh

# Windows
run.bat
```

That's it — `uv` will create an isolated environment, install Flask,
psutil, and pywebview, and open a native desktop window backed by the
platform's native webview (Edge WebView2 on Windows, WKWebView on macOS,
Qt WebEngine on Linux).

### Manual invocation

```bash
uv run system-monitor                 # standalone window (default)
uv run system-monitor --browser       # open in your default browser
uv run system-monitor --no-open       # headless: just run the HTTP server
uv run system-monitor --host 0.0.0.0  # expose to LAN
uv run system-monitor --port 8765     # pin to a specific port
```

You can also run it as a module: `uv run python -m system_monitor`.

### Installing as a CLI

```bash
uv tool install .
system-monitor
```

This makes `system-monitor` available globally on your `PATH`.

## Optional integrations

These are auto-detected at runtime. None are required to launch the app.

| Feature                  | How to enable                                                       |
| ------------------------ | ------------------------------------------------------------------- |
| GPU metrics (NVIDIA)     | Install the proprietary NVIDIA driver (`nvidia-smi` on `$PATH`).    |
| SMART data               | Install `smartmontools` (`smartctl` on `$PATH`).                    |
| RAM speed/slots (Linux)  | `dmidecode` (run with sudo permissions to populate).                |
| CPU temp (macOS)         | `brew install osx-cpu-temp`.                                        |
| Wi-Fi SSID (Linux)       | `iwgetid` from `wireless-tools`.                                    |

## Architecture

```
pyproject.toml              uv-managed deps + system-monitor CLI entry point
system_monitor/server.py    Flask + pywebview launcher (native window)
system_monitor/monitor.py   psutil-based collector with per-platform fallbacks
system_monitor/static/      Single-page dashboard (HTML/CSS/JS)
```

The native window hosts a tiny single-page app that polls a local
`/api/stats` endpoint every 1.5 seconds and updates SVG gauges, history
charts, and per-disk cards in place — no build step, no framework, no
bundler.

## License

MIT
