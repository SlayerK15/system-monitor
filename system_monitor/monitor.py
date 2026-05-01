"""Cross-platform system metrics collection.

Designed to run on Windows, macOS, and any Linux distribution. Every metric
is wrapped in defensive code so that missing sensors degrade to ``None``
rather than crashing the whole snapshot.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
from collections import deque
from threading import Lock
from typing import Any

import psutil

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

HISTORY_SIZE = 60  # seconds of sparkline history


def _safe(callable_, default=None):
    try:
        return callable_()
    except Exception:
        return default


def _run(cmd: list[str], timeout: float = 2.0) -> str | None:
    """Run a command and return stdout, or None if it fails or isn't installed."""
    if not shutil.which(cmd[0]):
        return None
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _human_bytes(n: float | None) -> str:
    if n is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} EB"


class SystemMonitor:
    def __init__(self, history_size: int = HISTORY_SIZE):
        self.history_size = history_size
        self.cpu_history: deque[float] = deque(maxlen=history_size)
        self.gpu_history: deque[float] = deque(maxlen=history_size)

        self._lock = Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_time = time.monotonic()
        self._last_disk_io = _safe(lambda: psutil.disk_io_counters(perdisk=True), {}) or {}
        self._last_disk_time = time.monotonic()
        self._session_start = time.time()
        self._session_initial_disk = _safe(psutil.disk_io_counters)

        # Cache for Windows-specific dynamic metrics that are too slow to
        # poll on every snapshot (each PowerShell launch costs ~300-500 ms).
        self._win_disk_temps_cache: dict[str, float] = {}
        self._win_disk_temps_at: float = 0.0

        # One-shot collection of platform-static info (CPU model, motherboard,
        # RAM speed/slots, battery design voltage, drive map, disk health).
        # Avoids re-launching PowerShell every frame on Windows.
        self._static = self._collect_static_info()

        # Prime cpu_percent so the first reading isn't 0.0.
        psutil.cpu_percent(interval=None)

    # ------------------------------------------------------------------
    # static info collection (run once, cached on the instance)

    def _collect_static_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {}
        if IS_WINDOWS:
            self._collect_windows_static(info)
        return info

    def _collect_windows_static(self, info: dict[str, Any]) -> None:
        # One PowerShell call gathers everything that doesn't change at
        # runtime. Cuts per-snapshot overhead from ~5 PS launches to 0.
        ps_script = (
            "$ErrorActionPreference='SilentlyContinue';"
            "$cpu=(Get-CimInstance Win32_Processor|Select-Object -First 1).Name;"
            "$b=Get-CimInstance Win32_BaseBoard;"
            "$mem=@(Get-CimInstance Win32_PhysicalMemory);"
            "$arr=Get-CimInstance Win32_PhysicalMemoryArray|Select-Object -First 1;"
            "$bat=Get-CimInstance Win32_Battery|Select-Object -First 1;"
            "$parts=@(Get-Partition|Where-Object DriveLetter);"
            "$disks=@(Get-PhysicalDisk);"
            "$out=[ordered]@{"
            "  cpu_model=$cpu;"
            "  motherboard=if($b){\"$($b.Manufacturer) $($b.Product)\".Trim()}else{$null};"
            "  memory_speed=if($mem.Count -gt 0){$mem[0].Speed}else{$null};"
            "  memory_slots_used=$mem.Count;"
            "  memory_slots_total=if($arr){$arr.MemoryDevices}else{$mem.Count};"
            "  battery_voltage_mv=if($bat){$bat.DesignVoltage}else{0};"
            "  drive_map=@($parts|ForEach-Object{@{letter=\"$($_.DriveLetter):\";drive=\"PhysicalDrive$($_.DiskNumber)\"}});"
            "  disk_health=@($disks|ForEach-Object{@{device=\"PhysicalDrive$($_.DeviceId)\";status=$_.HealthStatus}})"
            "};"
            "$out|ConvertTo-Json -Depth 4 -Compress"
        )
        out = _run(["powershell", "-NoProfile", "-Command", ps_script], timeout=10.0)
        if not out:
            return
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return
        info["cpu_model"] = data.get("cpu_model")
        info["motherboard"] = data.get("motherboard")
        speed = data.get("memory_speed")
        if speed:
            try:
                info["memory_speed"] = int(speed)
            except (TypeError, ValueError):
                pass
        used = data.get("memory_slots_used")
        total = data.get("memory_slots_total")
        if used:
            try:
                info["memory_slots"] = {
                    "used": int(used),
                    "total": int(total or used),
                }
            except (TypeError, ValueError):
                pass
        mv = data.get("battery_voltage_mv") or 0
        try:
            mv_int = int(mv)
            if mv_int > 0:
                info["battery_voltage"] = round(mv_int / 1000.0, 2)
        except (TypeError, ValueError):
            pass
        drive_map: dict[str, str] = {}
        for entry in data.get("drive_map") or []:
            if isinstance(entry, dict):
                letter = (entry.get("letter") or "").upper()
                drive = entry.get("drive")
                if letter and drive:
                    drive_map[letter] = drive
        info["windows_drive_map"] = drive_map
        disk_health: dict[str, str] = {}
        for entry in data.get("disk_health") or []:
            if isinstance(entry, dict):
                device = entry.get("device")
                status = entry.get("status")
                if device and status:
                    disk_health[device] = status
        info["windows_disk_health"] = disk_health

    # ------------------------------------------------------------------
    # public API

    def snapshot(self) -> dict[str, Any]:
        """Collect every metric for one frame."""
        with self._lock:
            cpu = self._cpu()
            gpu = self._gpu()
            self.cpu_history.append(cpu.get("utilization") or 0.0)
            self.gpu_history.append(gpu.get("utilization") or 0.0)

            return {
                "cpu": {**cpu, "history": list(self.cpu_history)},
                "gpu": {**gpu, "history": list(self.gpu_history)},
                "memory": self._memory(),
                "disks": self._disks(),
                "network": self._network(),
                "power": self._power(),
                "fans": self._fans(),
                "system": self._system(),
                "smart": self._smart(),
                "overall": self._overall(),
                "timestamp": time.time(),
            }

    # ------------------------------------------------------------------
    # CPU

    def _cpu(self) -> dict[str, Any]:
        utilization = _safe(lambda: psutil.cpu_percent(interval=None), 0.0)
        threads = _safe(lambda: psutil.cpu_count(logical=True))
        cores = _safe(lambda: psutil.cpu_count(logical=False))
        return {
            "model": self._cpu_model(),
            "utilization": utilization,
            "clock_ghz": self._cpu_clock_ghz(),
            "threads": threads,
            "cores": cores,
            "temperature_c": self._cpu_temperature(),
        }

    def _cpu_clock_ghz(self) -> float | None:
        # psutil.cpu_freq returns 0 on Apple Silicon and sometimes a tiny
        # bogus value, so filter anything below a sane CPU floor (100 MHz).
        freq = _safe(lambda: psutil.cpu_freq())
        if freq and freq.current and freq.current >= 100:
            return freq.current / 1000.0
        if IS_MAC:
            # Intel Macs expose hw.cpufrequency in Hz; Apple Silicon returns 0.
            out = _run(["sysctl", "-n", "hw.cpufrequency"])
            if out and out.strip().isdigit():
                hz = int(out.strip())
                if hz > 0:
                    return hz / 1e9
        return None

    def _cpu_model(self) -> str:
        if IS_WINDOWS and self._static.get("cpu_model"):
            return self._static["cpu_model"]
        if IS_LINUX:
            try:
                with open("/proc/cpuinfo", "r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.lower().startswith("model name"):
                            return line.split(":", 1)[1].strip()
            except OSError:
                pass
        if IS_MAC:
            out = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
            if out:
                return out.strip()
        if IS_WINDOWS:
            # Static-info fast path was empty; fall back to a one-shot lookup.
            out = _run([
                "powershell", "-NoProfile", "-Command",
                "(Get-CimInstance Win32_Processor).Name",
            ])
            if out:
                return out.strip()
        return platform.processor() or platform.machine() or "Unknown CPU"

    def _cpu_temperature(self) -> float | None:
        sensors = _safe(lambda: psutil.sensors_temperatures(), {}) or {}
        # Look at the most reliable sources first.
        priority = ("coretemp", "k10temp", "cpu_thermal", "zenpower", "acpitz")
        for key in priority:
            entries = sensors.get(key)
            if entries:
                temps = [e.current for e in entries if e.current]
                if temps:
                    return round(max(temps), 1)
        # Fall back to any sensor whose label looks CPU-ish.
        for entries in sensors.values():
            for e in entries:
                label = (getattr(e, "label", "") or "").lower()
                if "cpu" in label or "package" in label or "core" in label:
                    if e.current:
                        return round(e.current, 1)
        if IS_MAC:
            # osx-cpu-temp works on Intel Macs.
            # smctemp is a community tool that supports Apple Silicon.
            for cmd in (["osx-cpu-temp"], ["smctemp", "-c"], ["smctemp"]):
                out = _run(cmd)
                if not out:
                    continue
                m = re.search(r"([\d.]+)", out)
                if m:
                    t = float(m.group(1))
                    if t > 1:  # 0.0 means the SMC key wasn't readable.
                        return round(t, 1)
        if IS_WINDOWS:
            # ACPI thermal zones are the only built-in source; they often
            # report motherboard rather than CPU package temp, and may
            # require admin to access. Best-effort.
            out = _run([
                "powershell", "-NoProfile", "-Command",
                "$t=Get-CimInstance -Namespace 'root/wmi' -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue;"
                "if($t){(($t|Sort-Object CurrentTemperature -Descending|Select-Object -First 1).CurrentTemperature-2732)/10.0}",
            ], timeout=3.0)
            if out and out.strip():
                try:
                    t = float(out.strip())
                    if 0 < t < 150:
                        return round(t, 1)
                except ValueError:
                    pass
        return None

    # ------------------------------------------------------------------
    # GPU

    def _gpu(self) -> dict[str, Any]:
        info = self._gpu_nvidia()
        if info:
            return info
        info = self._gpu_apple()
        if info:
            return info
        return {
            "model": "No discrete GPU detected",
            "utilization": 0.0,
            "clock_ghz": None,
            "vram_used_gb": None,
            "vram_total_gb": None,
            "temperature_c": None,
            "available": False,
        }

    def _gpu_nvidia(self) -> dict[str, Any] | None:
        out = _run([
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,clocks.gr,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ])
        if not out:
            return None
        first = out.strip().splitlines()[0] if out.strip() else ""
        parts = [p.strip() for p in first.split(",")]
        if len(parts) < 6:
            return None
        try:
            return {
                "model": parts[0],
                "utilization": float(parts[1]),
                "clock_ghz": float(parts[2]) / 1000.0 if parts[2] not in ("", "[N/A]") else None,
                "vram_used_gb": float(parts[3]) / 1024.0,
                "vram_total_gb": float(parts[4]) / 1024.0,
                "temperature_c": float(parts[5]),
                "available": True,
            }
        except ValueError:
            return None

    def _gpu_apple(self) -> dict[str, Any] | None:
        if not IS_MAC:
            return None
        model = "Apple GPU"
        out = _run(["system_profiler", "-json", "SPDisplaysDataType"], timeout=5.0)
        if out:
            try:
                data = json.loads(out)
                displays = data.get("SPDisplaysDataType", [])
                if displays:
                    d = displays[0]
                    model = d.get("sppci_model") or d.get("_name") or "Apple GPU"
            except (json.JSONDecodeError, KeyError):
                pass

        # ioreg exposes GPU utilization on Apple Silicon without sudo.
        utilization = 0.0
        ioreg_out = _run(
            ["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"],
            timeout=2.0,
        )
        if ioreg_out:
            m = re.search(r'"Device Utilization %"\s*=\s*(\d+)', ioreg_out)
            if m:
                utilization = float(m.group(1))

        return {
            "model": model,
            "utilization": utilization,
            "clock_ghz": None,
            "vram_used_gb": None,
            "vram_total_gb": None,
            "temperature_c": None,
            "available": True,
        }

    # ------------------------------------------------------------------
    # Memory

    def _memory(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        sm = _safe(psutil.swap_memory)
        return {
            "percent": vm.percent,
            "used_gb": vm.used / (1024 ** 3),
            "total_gb": vm.total / (1024 ** 3),
            "available_gb": vm.available / (1024 ** 3),
            "speed_mhz": self._memory_speed(),
            "slots": self._memory_slots(),
            "committed_gb": (sm.used / (1024 ** 3)) if sm else None,
        }

    def _memory_speed(self) -> int | None:
        if IS_WINDOWS and self._static.get("memory_speed"):
            return self._static["memory_speed"]
        if IS_LINUX:
            out = _run(["sudo", "-n", "dmidecode", "-t", "memory"])
            if out:
                m = re.search(r"Configured Memory Speed:\s*(\d+)\s*MT/s", out)
                if m:
                    return int(m.group(1))
        if IS_MAC:
            out = _run(["system_profiler", "SPMemoryDataType"], timeout=3.0)
            if out:
                m = re.search(r"Speed:\s*(\d+)\s*MHz", out)
                if m:
                    return int(m.group(1))
        return None

    def _memory_slots(self) -> dict[str, int] | None:
        if IS_WINDOWS:
            return self._static.get("memory_slots")
        return None

    # ------------------------------------------------------------------
    # Disks

    def _disks(self) -> list[dict[str, Any]]:
        partitions = _safe(lambda: psutil.disk_partitions(all=False), []) or []
        # Filter out pseudo-filesystems that show up on Linux.
        skip_fstypes = {"squashfs", "tmpfs", "devtmpfs", "overlay", "proc", "sysfs"}
        results = []
        seen_devices: set[str] = set()
        now = time.monotonic()
        per_disk = _safe(lambda: psutil.disk_io_counters(perdisk=True), {}) or {}
        elapsed = max(now - self._last_disk_time, 1e-6)

        for part in partitions:
            if part.fstype in skip_fstypes:
                continue
            if part.device in seen_devices:
                continue
            seen_devices.add(part.device)
            usage = _safe(lambda p=part.mountpoint: psutil.disk_usage(p))
            if not usage:
                continue
            io_key = self._disk_io_key(part.device, per_disk.keys())
            cur = per_disk.get(io_key) if io_key else None
            prev = self._last_disk_io.get(io_key) if io_key else None
            read_speed = write_speed = None
            if cur and prev:
                read_speed = max(0.0, (cur.read_bytes - prev.read_bytes) / elapsed)
                write_speed = max(0.0, (cur.write_bytes - prev.write_bytes) / elapsed)
            results.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "label": self._disk_label(part),
                "model": self._disk_model(part.device),
                "percent": usage.percent,
                "used_gb": usage.used / (1024 ** 3),
                "total_gb": usage.total / (1024 ** 3),
                "read_bps": read_speed,
                "write_bps": write_speed,
                "temperature_c": self._disk_temperature(part.device),
                "health": self._disk_health(part.device),
            })

        self._last_disk_io = per_disk
        self._last_disk_time = now

        # Stable order: largest first so the dashboard layout doesn't jump.
        results.sort(key=lambda d: d["total_gb"], reverse=True)
        return results

    def _disk_io_key(self, device: str, candidate_keys=()) -> str | None:
        """Map a partition device path to its psutil disk_io_counters key.

        psutil keys disks by physical-device name. Names differ widely
        between platforms — Linux uses ``sda`` / ``nvme0n1``, macOS uses
        ``disk0`` (APFS partitions show as ``disk3s1s1``), Windows uses
        ``PhysicalDrive0``. Try a regex-derived candidate first, then
        fall back to the longest perdisk key that prefixes the device
        basename.
        """
        if not device:
            return None
        # Windows partitions are exposed as drive letters like "C:\\"; psutil
        # keys disk I/O by "PhysicalDriveN", so we need a partition-table
        # map. Cached at startup in self._static.
        if IS_WINDOWS:
            letter = device[:2].upper()
            drive = self._static.get("windows_drive_map", {}).get(letter)
            if drive:
                return drive
            return None
        name = os.path.basename(device)
        candidates = []
        # macOS APFS: diskNsM[sK] -> diskN
        m = re.match(r"^(disk\d+)", name)
        if m:
            candidates.append(m.group(1))
        # Linux NVMe: nvme0n1p1 -> nvme0n1
        m = re.match(r"^(nvme\d+n\d+)", name)
        if m:
            candidates.append(m.group(1))
        # Linux mmc / md: mmcblk0p1 -> mmcblk0
        m = re.match(r"^(mmcblk\d+|md\d+)", name)
        if m:
            candidates.append(m.group(1))
        # Plain sda1 -> sda
        m = re.match(r"^([a-zA-Z]+)\d*$", name)
        if m:
            candidates.append(m.group(1))
        candidates.append(name)

        keys = list(candidate_keys)
        for c in candidates:
            if c in keys:
                return c
        # Last-resort: pick the longest psutil key that the device name starts with.
        prefixed = [k for k in keys if k and name.startswith(k)]
        if prefixed:
            return max(prefixed, key=len)
        return candidates[0] if candidates else None

    def _disk_label(self, part) -> str:
        if IS_WINDOWS:
            return part.device.rstrip("\\")  # e.g. "C:"
        return part.mountpoint

    def _disk_model(self, device: str) -> str | None:
        if IS_LINUX:
            base = os.path.basename(re.sub(r"\d+$", "", device))
            model_path = f"/sys/block/{base}/device/model"
            try:
                with open(model_path, "r", encoding="utf-8") as fh:
                    return fh.read().strip() or None
            except OSError:
                return None
        return None

    def _disk_temperature(self, device: str) -> float | None:
        # Try smartctl - works on Linux/Mac/Windows when smartmontools is installed.
        out = _run(["smartctl", "-A", "-j", device], timeout=3.0)
        if out:
            try:
                data = json.loads(out)
                temp = data.get("temperature", {}).get("current")
                if temp is not None:
                    return float(temp)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        # Linux NVMe has thermal zone exposed via psutil.
        if IS_LINUX:
            sensors = _safe(lambda: psutil.sensors_temperatures(), {}) or {}
            for key in ("nvme", "drivetemp"):
                entries = sensors.get(key)
                if entries:
                    temps = [e.current for e in entries if e.current]
                    if temps:
                        return round(max(temps), 1)
        if IS_WINDOWS:
            temps = self._windows_disk_temps()
            letter = device[:2].upper()
            drive = self._static.get("windows_drive_map", {}).get(letter)
            if drive and drive in temps:
                return temps[drive]
        return None

    def _windows_disk_temps(self) -> dict[str, float]:
        # Get-StorageReliabilityCounter is slow (~1-2s). Refresh at most every
        # 30 seconds — drive temps don't change quickly anyway.
        if not IS_WINDOWS:
            return {}
        now = time.monotonic()
        if self._win_disk_temps_cache and now - self._win_disk_temps_at < 30:
            return self._win_disk_temps_cache
        out = _run([
            "powershell", "-NoProfile", "-Command",
            "$ErrorActionPreference='SilentlyContinue';"
            "Get-PhysicalDisk|ForEach-Object{"
            "  $r=$_|Get-StorageReliabilityCounter;"
            "  if($r){\"PhysicalDrive$($_.DeviceId)=$($r.Temperature)\"}"
            "}",
        ], timeout=5.0)
        result: dict[str, float] = {}
        if out:
            for line in out.splitlines():
                line = line.strip()
                if "=" not in line:
                    continue
                drive, value = line.split("=", 1)
                value = value.strip()
                if value and value.lstrip("-").isdigit():
                    t = int(value)
                    if 0 < t < 150:
                        result[drive.strip()] = float(t)
        self._win_disk_temps_cache = result
        self._win_disk_temps_at = now
        return result

    def _disk_health(self, device: str) -> str | None:
        out = _run(["smartctl", "-H", "-j", device], timeout=3.0)
        if out:
            try:
                data = json.loads(out)
                passed = data.get("smart_status", {}).get("passed")
                if passed is True:
                    return "Good"
                if passed is False:
                    return "Failing"
            except (json.JSONDecodeError, KeyError):
                pass
        if IS_WINDOWS:
            letter = device[:2].upper()
            drive = self._static.get("windows_drive_map", {}).get(letter)
            if drive:
                status = self._static.get("windows_disk_health", {}).get(drive)
                if status == "Healthy":
                    return "Good"
                if status:
                    return status
        return None

    # ------------------------------------------------------------------
    # Network

    def _network(self) -> dict[str, Any]:
        cur = psutil.net_io_counters()
        now = time.monotonic()
        elapsed = max(now - self._last_net_time, 1e-6)
        download_bps = max(0.0, (cur.bytes_recv - self._last_net.bytes_recv) / elapsed)
        upload_bps = max(0.0, (cur.bytes_sent - self._last_net.bytes_sent) / elapsed)
        self._last_net = cur
        self._last_net_time = now

        ip, iface = self._primary_ip()
        connected = ip is not None and not ip.startswith("127.")
        latency = self._ping_latency() if connected else None
        signal = self._wifi_signal(iface)

        return {
            "connected": connected,
            "ssid": self._wifi_ssid(iface),
            "interface": iface,
            "download_bps": download_bps,
            "upload_bps": upload_bps,
            "ip": ip,
            "latency_ms": latency,
            "signal": signal,
        }

    def _primary_ip(self) -> tuple[str | None, str | None]:
        # Open a UDP socket to a public IP - no packet is sent, but the kernel
        # picks the egress interface, revealing our LAN IP.
        ip = None
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(0.2)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
        except OSError:
            ip = None

        iface = None
        if ip:
            addrs = _safe(psutil.net_if_addrs, {}) or {}
            for name, entries in addrs.items():
                for addr in entries:
                    if addr.address == ip:
                        iface = name
                        break
                if iface:
                    break
        return ip, iface

    def _ping_latency(self) -> float | None:
        if IS_WINDOWS:
            # -w wait time (ms)
            cmd = ["ping", "-n", "1", "-w", "1000", "8.8.8.8"]
        elif IS_MAC:
            # macOS: -W is per-reply wait in MILLISECONDS (so -W 1 means 1ms,
            # which always fails). Use -t for total timeout in seconds.
            cmd = ["ping", "-c", "1", "-t", "1", "8.8.8.8"]
        else:
            # Linux: -W is per-reply wait in seconds.
            cmd = ["ping", "-c", "1", "-W", "1", "8.8.8.8"]
        out = _run(cmd, timeout=2.0)
        if not out:
            return None
        m = re.search(r"time[=<]\s*([\d.]+)\s*ms", out)
        if m:
            return float(m.group(1))
        return None

    def _wifi_ssid(self, iface: str | None) -> str | None:
        if IS_LINUX:
            out = _run(["iwgetid", "-r"])
            if out and out.strip():
                return out.strip()
        if IS_MAC:
            # The legacy `airport` binary was removed in modern macOS, so try
            # `networksetup` first which works on every supported release.
            if iface:
                out = _run(["networksetup", "-getairportnetwork", iface])
                if out:
                    m = re.search(r"Current Wi-Fi Network:\s*(.+)", out)
                    if m:
                        return m.group(1).strip()
            airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
            if os.path.exists(airport):
                out = _run([airport, "-I"])
                if out:
                    m = re.search(r"\bSSID:\s*(.+)", out)
                    if m:
                        return m.group(1).strip()
        if IS_WINDOWS:
            out = _run(["netsh", "wlan", "show", "interfaces"])
            if out:
                m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.MULTILINE)
                if m:
                    return m.group(1).strip()
        return None

    def _wifi_signal(self, iface: str | None) -> dict[str, Any] | None:
        # Returns {"label": "Excellent", "percent": 90} or None.
        percent = None
        if IS_LINUX:
            try:
                with open("/proc/net/wireless", "r", encoding="utf-8") as fh:
                    for line in fh.readlines()[2:]:
                        cols = line.split()
                        if not cols:
                            continue
                        # quality is column 2, e.g. "70."
                        q = cols[2].rstrip(".")
                        if q.replace(".", "").isdigit():
                            percent = min(100.0, float(q) / 70.0 * 100.0)
                            break
            except OSError:
                pass
        if IS_WINDOWS:
            out = _run(["netsh", "wlan", "show", "interfaces"])
            if out:
                m = re.search(r"Signal\s*:\s*(\d+)\s*%", out)
                if m:
                    percent = float(m.group(1))
        if percent is None:
            return None
        if percent >= 75:
            label = "Excellent"
        elif percent >= 50:
            label = "Good"
        elif percent >= 25:
            label = "Fair"
        else:
            label = "Weak"
        return {"label": label, "percent": round(percent)}

    # ------------------------------------------------------------------
    # Power

    def _power(self) -> dict[str, Any]:
        battery = _safe(lambda: psutil.sensors_battery())
        if not battery:
            return {
                "has_battery": False,
                "ac_connected": True,
                "percent": None,
                "time_remaining": None,
                "power_plan": self._power_plan(),
                "voltage_v": None,
                "current_a": None,
                "power_w": None,
                "charging": None,
            }
        secs = battery.secsleft
        if secs in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) or secs is None or secs < 0:
            time_remaining = None
        else:
            hours, rem = divmod(secs, 3600)
            minutes = rem // 60
            time_remaining = f"{hours}h {minutes:02d}m"
        return {
            "has_battery": True,
            "ac_connected": battery.power_plugged,
            "charging": battery.power_plugged and battery.percent < 100,
            "percent": round(battery.percent, 1),
            "time_remaining": time_remaining,
            "power_plan": self._power_plan(),
            "voltage_v": self._battery_voltage(),
            "current_a": None,
            "power_w": None,
        }

    def _power_plan(self) -> str | None:
        if IS_WINDOWS:
            out = _run(["powercfg", "/getactivescheme"])
            if out:
                m = re.search(r"\(([^)]+)\)\s*$", out.strip())
                if m:
                    return m.group(1)
        if IS_LINUX:
            out = _run(["powerprofilesctl", "get"])
            if out:
                return out.strip().title()
        if IS_MAC:
            return None
        return None

    def _battery_voltage(self) -> float | None:
        if IS_LINUX:
            for path in ("/sys/class/power_supply/BAT0/voltage_now",
                         "/sys/class/power_supply/BAT1/voltage_now"):
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        return round(int(fh.read().strip()) / 1_000_000, 2)
                except (OSError, ValueError):
                    continue
        if IS_WINDOWS:
            # Win32_Battery exposes design voltage (mV); live voltage isn't
            # available without third-party drivers.
            return self._static.get("battery_voltage")
        return None

    # ------------------------------------------------------------------
    # Fans

    def _fans(self) -> list[dict[str, Any]]:
        fans = _safe(lambda: psutil.sensors_fans(), {}) or {}
        results = []
        max_rpm = 4000  # rough upper bound used to compute a percent visualization
        for chip, entries in fans.items():
            for entry in entries:
                label = (entry.label or chip).strip()
                rpm = entry.current
                results.append({
                    "label": self._friendly_fan_label(label),
                    "rpm": rpm,
                    "percent": min(100, round((rpm / max_rpm) * 100)) if rpm else 0,
                })
        return results

    def _friendly_fan_label(self, raw: str) -> str:
        lower = raw.lower()
        if "gpu" in lower:
            return "GPU Fan"
        if "cpu" in lower:
            return "CPU Fan"
        if "case" in lower or "chassis" in lower or "sys" in lower:
            return "Case Fan"
        return raw or "Fan"

    # ------------------------------------------------------------------
    # System

    def _system(self) -> dict[str, Any]:
        boot = psutil.boot_time()
        uptime_s = int(time.time() - boot)
        return {
            "system": self._os_pretty_name(),
            "kernel": platform.release(),
            "hostname": socket.gethostname(),
            "architecture": platform.machine(),
            "motherboard": self._motherboard(),
            "uptime_s": uptime_s,
            "uptime_human": self._format_uptime(uptime_s),
            "last_updated": time.strftime("%H:%M:%S"),
        }

    def _os_pretty_name(self) -> str:
        if IS_LINUX:
            try:
                with open("/etc/os-release", "r", encoding="utf-8") as fh:
                    fields = {}
                    for line in fh:
                        if "=" in line:
                            k, v = line.strip().split("=", 1)
                            fields[k] = v.strip('"')
                    name = fields.get("PRETTY_NAME") or fields.get("NAME")
                    if name:
                        return f"{name} {platform.machine()}".strip()
            except OSError:
                pass
            return f"Linux {platform.release()}"
        if IS_MAC:
            ver = platform.mac_ver()[0] or platform.release()
            return f"macOS {ver}"
        if IS_WINDOWS:
            return f"{platform.system()} {platform.release()} {platform.version()}"
        return f"{platform.system()} {platform.release()}"

    def _motherboard(self) -> str | None:
        if IS_LINUX:
            try:
                vendor = open("/sys/class/dmi/id/board_vendor").read().strip()
                name = open("/sys/class/dmi/id/board_name").read().strip()
                if vendor or name:
                    return " ".join(p for p in (vendor, name) if p)
            except OSError:
                pass
        if IS_WINDOWS:
            cached = self._static.get("motherboard")
            if cached:
                return cached
            out = _run([
                "powershell", "-NoProfile", "-Command",
                "$b = Get-CimInstance Win32_BaseBoard; \"$($b.Manufacturer) $($b.Product)\"",
            ])
            if out:
                return out.strip()
        if IS_MAC:
            out = _run(["sysctl", "-n", "hw.model"])
            if out:
                return out.strip()
        return None

    def _format_uptime(self, seconds: int) -> str:
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days:
            return f"{days}d {hours}h {minutes}m"
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    # ------------------------------------------------------------------
    # SMART

    def _smart(self) -> dict[str, Any] | None:
        # Pick the first physical disk we can query. Anything more is best
        # represented in the per-disk cards above.
        if IS_WINDOWS:
            candidates = [r"\\.\PhysicalDrive0"]
        elif IS_MAC:
            candidates = ["/dev/disk0"]
        else:
            candidates = ["/dev/nvme0n1", "/dev/sda", "/dev/nvme0", "/dev/vda"]

        for dev in candidates:
            out = _run(["smartctl", "-a", "-j", dev], timeout=3.0)
            if not out:
                continue
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                continue
            passed = data.get("smart_status", {}).get("passed")
            health = "Good" if passed else ("Failing" if passed is False else "Unknown")
            attrs = {a.get("name"): a for a in data.get("ata_smart_attributes", {}).get("table", [])}
            reallocated = None
            power_on_hours = None
            if "Reallocated_Sector_Ct" in attrs:
                reallocated = attrs["Reallocated_Sector_Ct"].get("raw", {}).get("value")
            if "Power_On_Hours" in attrs:
                power_on_hours = attrs["Power_On_Hours"].get("raw", {}).get("value")
            # NVMe path
            if power_on_hours is None:
                power_on_hours = data.get("power_on_time", {}).get("hours")
            temp = data.get("temperature", {}).get("current")
            return {
                "device": dev,
                "health": health,
                "reallocated_sectors": reallocated,
                "power_on_hours": power_on_hours,
                "temperature_c": temp,
                "status": "OK" if passed else "Check",
            }
        return None

    # ------------------------------------------------------------------
    # Overall

    def _overall(self) -> dict[str, Any]:
        cur = _safe(psutil.disk_io_counters)
        read_total = write_total = None
        if cur and self._session_initial_disk:
            read_total = cur.read_bytes
            write_total = cur.write_bytes
        return {
            "healthy": True,  # populated client-side from individual signals
            "uptime_human": self._format_uptime(int(time.time() - psutil.boot_time())),
            "data_read": _human_bytes(read_total),
            "data_written": _human_bytes(write_total),
        }
