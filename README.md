# Performance Monitor

A cross-platform system monitor with a clean, modern dashboard. Runs on
**Windows 10/11**, **macOS**, and **any Linux distribution**.

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

Sensors that aren't available on your platform gracefully degrade to "—" rather
than crashing the dashboard.

## Quick start

### Linux / macOS

```bash
./run.sh
```

### Windows

```bat
run.bat
```

The script creates a virtual environment, installs dependencies, and opens the
dashboard at <http://127.0.0.1:8765> in your browser.

### Manual install

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
python app.py
```

### Command-line options

```
python app.py --host 127.0.0.1 --port 8765 --no-browser
```

| Option         | Default     | Description                                   |
| -------------- | ----------- | --------------------------------------------- |
| `--host`       | `127.0.0.1` | Bind address. Use `0.0.0.0` to expose on LAN. |
| `--port`       | `8765`      | TCP port.                                     |
| `--no-browser` | off         | Don't auto-open the browser.                  |

## Optional integrations

These are auto-detected. None are required.

| Feature                | How to enable                                                     |
| ---------------------- | ----------------------------------------------------------------- |
| GPU metrics (NVIDIA)   | Install the proprietary NVIDIA driver (`nvidia-smi` on `$PATH`).  |
| SMART data             | Install `smartmontools` (`smartctl` on `$PATH`).                  |
| RAM speed/slots (Linux)| `dmidecode` (run with sudo permissions if you want this populated). |
| CPU temp (macOS)       | `brew install osx-cpu-temp`.                                       |
| Wi-Fi SSID (Linux)     | `iwgetid` from `wireless-tools`.                                   |

## Architecture

```
app.py                      Flask entrypoint, --host/--port/--no-browser
system_monitor/monitor.py   psutil-based collector with per-platform fallbacks
static/index.html           Single-page dashboard
static/style.css            Windows 11-inspired theme
static/app.js               Polls /api/stats every 1.5s and renders SVG charts
```

The backend exposes a single JSON endpoint at `/api/stats` that returns a full
snapshot. The front-end polls it every 1.5 seconds and updates DOM/SVG in
place — no build step, no framework, no native dependencies.

## License

MIT
