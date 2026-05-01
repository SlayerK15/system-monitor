/* Performance Monitor — front-end rendering & polling. */
(() => {
  "use strict";

  const POLL_INTERVAL_MS = 1500;
  const SVG_NS = "http://www.w3.org/2000/svg";

  const netHistory = { down: [], up: [] };
  const NET_HISTORY_SIZE = 60;

  // -------------------- helpers --------------------
  const $ = (id) => document.getElementById(id);

  function fmtBps(bps) {
    if (bps == null) return "—";
    const units = ["B/s", "KB/s", "MB/s", "GB/s"];
    let i = 0;
    let v = bps;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
  }

  function fmtBitRate(bps) {
    // Networking values look more familiar in bits per second.
    if (bps == null) return "—";
    const bits = bps * 8;
    const units = ["bps", "Kbps", "Mbps", "Gbps"];
    let i = 0;
    let v = bits;
    while (v >= 1000 && i < units.length - 1) { v /= 1000; i++; }
    return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
  }

  function fmtNumber(n, digits = 0) {
    if (n == null || Number.isNaN(n)) return "—";
    return Number(n).toLocaleString(undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function setText(id, value) {
    const el = $(id);
    if (el && el.textContent !== value) el.textContent = value;
  }

  // -------------------- gauge (semi-circle) --------------------
  function buildGauge(container, accentColor) {
    container.innerHTML = "";
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 200 120");
    const trackPath = "M20,110 A80,80 0 0,1 180,110";

    const track = document.createElementNS(SVG_NS, "path");
    track.setAttribute("d", trackPath);
    track.setAttribute("stroke", "#e5edf5");
    track.setAttribute("stroke-width", "14");
    track.setAttribute("stroke-linecap", "round");
    track.setAttribute("fill", "none");

    const value = document.createElementNS(SVG_NS, "path");
    value.setAttribute("d", trackPath);
    value.setAttribute("stroke", accentColor);
    value.setAttribute("stroke-width", "14");
    value.setAttribute("stroke-linecap", "round");
    value.setAttribute("fill", "none");
    value.setAttribute("stroke-dasharray", "0 1000");

    svg.appendChild(track);
    svg.appendChild(value);
    container.appendChild(svg);

    const overlay = document.createElement("div");
    overlay.className = "gauge-text";
    overlay.innerHTML = `
      <div class="gauge-value"><span class="num">0</span><span class="unit">%</span></div>
      <div class="gauge-label">Utilization</div>`;
    container.appendChild(overlay);

    // Once attached, measure path length precisely so the dash math is correct.
    const length = value.getTotalLength();
    return {
      update(percent) {
        const p = Math.max(0, Math.min(100, percent || 0));
        value.setAttribute("stroke-dasharray", `${(p / 100) * length} ${length}`);
        overlay.querySelector(".num").textContent = Math.round(p);
      },
    };
  }

  // -------------------- chart --------------------
  function buildChart(container, color) {
    container.innerHTML = "";
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 600 110");
    svg.setAttribute("preserveAspectRatio", "none");

    const gradId = `grad-${Math.random().toString(36).slice(2)}`;
    svg.innerHTML = `
      <defs>
        <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${color}" stop-opacity="0.35"/>
          <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <path class="chart-fill" fill="url(#${gradId})" d=""/>
      <path class="chart-line" stroke="${color}" stroke-width="1.6" fill="none" d=""/>
    `;

    container.appendChild(svg);

    const axis = document.createElement("div");
    axis.className = "chart-axis";
    axis.innerHTML = `
      <span class="y-label" style="top:6%">100%</span>
      <span class="y-label" style="top:30%">75%</span>
      <span class="y-label" style="top:54%">50%</span>
      <span class="y-label" style="top:78%">25%</span>
      <span class="y-label" style="top:96%">0%</span>
      <span class="x-label" style="left:8%">60 sec</span>
      <span class="x-label" style="left:32%">45 sec</span>
      <span class="x-label" style="left:55%">30 sec</span>
      <span class="x-label" style="left:78%">15 sec</span>
      <span class="x-label" style="left:97%">0 sec</span>
    `;
    container.appendChild(axis);

    const line = svg.querySelector(".chart-line");
    const fill = svg.querySelector(".chart-fill");

    return {
      update(values) {
        if (!values || !values.length) return;
        const w = 600;
        const h = 110;
        const N = 60;
        // Right-align the data so newest sample sits at x = w.
        const padded = values.length >= N
          ? values.slice(-N)
          : Array(N - values.length).fill(values[0]).concat(values);
        const stepX = w / (N - 1);
        const points = padded.map((v, i) => {
          const x = i * stepX;
          const y = h - (Math.max(0, Math.min(100, v)) / 100) * h;
          return [x, y];
        });
        const linePath = points
          .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
          .join(" ");
        const fillPath = `${linePath} L${w},${h} L0,${h} Z`;
        line.setAttribute("d", linePath);
        fill.setAttribute("d", fillPath);
      },
    };
  }

  // -------------------- mini gauge for fans --------------------
  function miniGaugeSVG(percent, color) {
    const p = Math.max(0, Math.min(100, percent || 0));
    const r = 22;
    const c = 2 * Math.PI * r;
    return `
      <svg viewBox="0 0 56 56">
        <circle cx="28" cy="28" r="${r}" stroke="#e5edf5" stroke-width="6" fill="none"/>
        <circle cx="28" cy="28" r="${r}" stroke="${color}" stroke-width="6" fill="none"
                stroke-linecap="round"
                stroke-dasharray="${(p / 100) * c} ${c}"
                transform="rotate(-90 28 28)"/>
      </svg>
      <div class="pct">${Math.round(p)}%</div>
    `;
  }

  // -------------------- sparklines for network --------------------
  function drawSparkline(svgEl, values, color) {
    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);
    if (!values.length) return;
    const max = Math.max(...values, 1);
    const w = 200;
    const h = 40;
    const stepX = w / Math.max(values.length - 1, 1);
    let d = "";
    values.forEach((v, i) => {
      const x = i * stepX;
      const y = h - (v / max) * (h - 4) - 2;
      d += `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)} `;
    });
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d.trim());
    path.setAttribute("stroke", color);
    path.setAttribute("stroke-width", "1.4");
    path.setAttribute("fill", "none");
    svgEl.appendChild(path);
  }

  // -------------------- disk cards --------------------
  function renderDisks(disks) {
    const row = $("storage-row");
    // Remove existing dynamically rendered disk cards (preserve RAM card).
    row.querySelectorAll('[data-dynamic="disk"]').forEach((el) => el.remove());

    // Cap to 2 disks so the 3-column row always fits.
    disks.slice(0, 2).forEach((disk) => {
      const card = document.createElement("article");
      card.className = "card storage-card";
      card.dataset.dynamic = "disk";

      const label = disk.label || disk.mountpoint || disk.device || "Disk";
      const total = disk.total_gb >= 1024
        ? `${(disk.total_gb / 1024).toFixed(1)} TB`
        : `${disk.total_gb.toFixed(0)} GB`;
      const used = disk.used_gb >= 1024
        ? `${(disk.used_gb / 1024).toFixed(1)} TB`
        : `${disk.used_gb.toFixed(0)} GB`;
      const accent = disk.percent >= 85 ? "red" : (disk.percent >= 70 ? "amber" : "blue");

      card.innerHTML = `
        <header class="row spread">
          <div class="row gap"><span class="badge blue">💾 ${label}</span></div>
          <span class="value-large">${disk.percent.toFixed(0)}%</span>
        </header>
        <p class="muted">${disk.model || disk.fstype || "Storage"}<br/>${used} / ${total}</p>
        <div class="bar"><div class="bar-fill ${accent}" style="width:${disk.percent}%"></div></div>
        <div class="stat-row small">
          <div class="stat">
            <div class="stat-value">${fmtBps(disk.read_bps)}</div>
            <div class="stat-label">Read Speed</div>
          </div>
          <div class="stat">
            <div class="stat-value">${fmtBps(disk.write_bps)}</div>
            <div class="stat-label">Write Speed</div>
          </div>
          <div class="stat">
            <div class="stat-value">${disk.temperature_c != null ? `${disk.temperature_c.toFixed(0)} °C` : "—"}</div>
            <div class="stat-label">Temperature</div>
          </div>
          <div class="stat">
            <div class="stat-value ${disk.health === "Good" ? "ok" : ""}">${disk.health || "—"}</div>
            <div class="stat-label">Health</div>
          </div>
        </div>
      `;
      row.appendChild(card);
    });
  }

  // -------------------- fans --------------------
  function renderFans(fans) {
    const row = $("fans-row");
    if (!fans.length) {
      row.innerHTML = '<div class="muted">No fan sensors available</div>';
      return;
    }
    row.innerHTML = fans
      .map((fan) => `
        <div class="fan-card">
          <div class="fan-info">
            <div class="fan-rpm">${fan.rpm ?? 0}<span class="unit small muted"> RPM</span></div>
            <div class="fan-label">${fan.label}</div>
          </div>
          <div class="mini-gauge">${miniGaugeSVG(fan.percent, "#2563eb")}</div>
        </div>
      `).join("");
  }

  // -------------------- smart --------------------
  function renderSmart(smart) {
    const row = $("smart-row");
    if (!smart) {
      row.innerHTML = '<div class="muted">SMART data unavailable (install smartmontools to enable)</div>';
      return;
    }
    const ok = smart.health === "Good";
    const tile = (label, value, ok = true) => `
      <div class="smart-tile">
        <span class="${ok ? "ok" : ""}">●</span>
        <div>
          <div class="smart-label">${label}</div>
          <div class="smart-value">${value ?? "—"}</div>
        </div>
      </div>
    `;
    row.innerHTML = [
      tile("Overall Health", smart.health || "Unknown", ok),
      tile("Reallocated Sectors", smart.reallocated_sectors ?? 0, (smart.reallocated_sectors ?? 0) === 0),
      tile("Power On Hours", smart.power_on_hours != null ? `${smart.power_on_hours} h` : "—"),
      tile("Temperature", smart.temperature_c != null ? `${smart.temperature_c} °C` : "—"),
      tile("Drive Status", smart.status || "OK", ok),
    ].join("");
  }

  // -------------------- main update --------------------
  const cpuGauge = buildGauge(document.getElementById("cpu-gauge"), "#2563eb");
  const gpuGauge = buildGauge(document.getElementById("gpu-gauge"), "#16a34a");
  const cpuChart = buildChart(document.getElementById("cpu-chart"), "#2563eb");
  const gpuChart = buildChart(document.getElementById("gpu-chart"), "#16a34a");

  function update(snapshot) {
    // CPU
    setText("cpu-model", snapshot.cpu.model || "—");
    cpuGauge.update(snapshot.cpu.utilization);
    setText("cpu-clock", snapshot.cpu.clock_ghz ? `${snapshot.cpu.clock_ghz.toFixed(2)} GHz` : "—");
    setText("cpu-threads", snapshot.cpu.threads ?? "—");
    setText("cpu-temp", snapshot.cpu.temperature_c != null ? `${snapshot.cpu.temperature_c.toFixed(0)} °C` : "—");
    cpuChart.update(snapshot.cpu.history);

    // GPU
    setText("gpu-model", snapshot.gpu.model || "—");
    gpuGauge.update(snapshot.gpu.utilization);
    setText("gpu-clock", snapshot.gpu.clock_ghz ? `${snapshot.gpu.clock_ghz.toFixed(2)} GHz` : "—");
    if (snapshot.gpu.vram_total_gb) {
      setText("gpu-vram", `${snapshot.gpu.vram_used_gb.toFixed(1)} / ${snapshot.gpu.vram_total_gb.toFixed(0)} GB`);
    } else {
      setText("gpu-vram", "—");
    }
    setText("gpu-temp", snapshot.gpu.temperature_c != null ? `${snapshot.gpu.temperature_c.toFixed(0)} °C` : "—");
    gpuChart.update(snapshot.gpu.history);

    // RAM
    const mem = snapshot.memory;
    setText("ram-percent", `${mem.percent.toFixed(0)}%`);
    setText("ram-usage", `${mem.used_gb.toFixed(1)} / ${mem.total_gb.toFixed(0)} GB`);
    document.getElementById("ram-bar").style.width = `${mem.percent}%`;
    setText("ram-speed", mem.speed_mhz ? `${mem.speed_mhz} MHz` : "—");
    setText("ram-slots", mem.slots ? `${mem.slots.used} / ${mem.slots.total}` : "—");
    setText("ram-committed", mem.committed_gb != null ? `${mem.committed_gb.toFixed(1)} GB` : "—");

    // Disks
    renderDisks(snapshot.disks || []);

    // Network
    const net = snapshot.network;
    setText("net-status", net.connected ? "Connected" : "Offline");
    document.getElementById("net-status").style.color = net.connected ? "var(--green)" : "var(--red)";
    setText("net-conn-type", net.ssid ? `Wi-Fi • ${net.ssid}` : (net.interface || "—"));
    setText("net-down", fmtBitRate(net.download_bps));
    setText("net-up", fmtBitRate(net.upload_bps));
    setText("net-latency", net.latency_ms != null ? `${net.latency_ms.toFixed(0)} ms` : "—");
    setText("net-ip", net.ip || "—");
    setText("net-signal", net.signal ? `${net.signal.label}` : (net.connected ? "Wired" : "—"));

    netHistory.down.push(net.download_bps || 0);
    netHistory.up.push(net.upload_bps || 0);
    if (netHistory.down.length > NET_HISTORY_SIZE) netHistory.down.shift();
    if (netHistory.up.length > NET_HISTORY_SIZE) netHistory.up.shift();
    drawSparkline(document.getElementById("net-down-spark"), netHistory.down, "#2563eb");
    drawSparkline(document.getElementById("net-up-spark"), netHistory.up, "#16a34a");

    // Power
    const pw = snapshot.power;
    if (pw.has_battery) {
      setText("power-source", pw.ac_connected ? "AC Connected" : "On Battery");
      setText("power-state", pw.charging ? "Charging" : (pw.ac_connected ? "Plugged in" : "Discharging"));
      setText("battery-percent", pw.percent != null ? `${pw.percent.toFixed(0)}%` : "—");
      document.getElementById("battery-bar").style.width = `${pw.percent || 0}%`;
      setText("battery-time", pw.time_remaining || (pw.ac_connected ? "Plugged in" : "—"));
    } else {
      setText("power-source", "AC Powered");
      setText("power-state", "Desktop");
      setText("battery-percent", "—");
      document.getElementById("battery-bar").style.width = "100%";
      setText("battery-time", "—");
    }
    setText("power-plan", pw.power_plan || "—");
    setText("power-voltage", pw.voltage_v != null ? `${pw.voltage_v.toFixed(1)} V` : "—");
    setText("power-current", pw.current_a != null ? `${pw.current_a.toFixed(2)} A` : "—");
    setText("power-watts", pw.power_w != null ? `${pw.power_w.toFixed(1)} W` : "—");

    // Fans
    renderFans(snapshot.fans || []);

    // System
    const sys = snapshot.system;
    setText("sys-os", sys.system || "—");
    setText("sys-board", sys.motherboard || "—");
    setText("sys-uptime", sys.uptime_human || "—");
    setText("sys-updated", sys.last_updated || "—");

    // SMART
    renderSmart(snapshot.smart);

    // Footer
    const overall = snapshot.overall;
    const cpuPct = snapshot.cpu.utilization || 0;
    const cpuTemp = snapshot.cpu.temperature_c || 0;
    const memPct = mem.percent;
    const healthy = cpuPct < 95 && memPct < 95 && cpuTemp < 90;
    const dot = document.querySelector(".footer .dot");
    dot.classList.toggle("green", healthy);
    dot.classList.toggle("amber", !healthy);
    setText("footer-status", healthy ? "System Healthy" : "Heavy Load");
    setText("footer-status-sub", healthy ? "All systems normal" : "Some metrics elevated");
    setText("footer-uptime", overall.uptime_human || "—");
    setText("footer-read", overall.data_read || "—");
    setText("footer-written", overall.data_written || "—");

    // Activity dots: 0..6 lit based on combined load.
    const load = Math.round((cpuPct + memPct) / 2 / 100 * 6);
    const dots = document.getElementById("footer-activity");
    dots.innerHTML = Array.from({ length: 6 }, (_, i) => `<i class="${i < load ? "on" : ""}"></i>`).join("");
  }

  // -------------------- polling --------------------
  let inFlight = false;

  async function poll() {
    if (inFlight) return;
    inFlight = true;
    try {
      const res = await fetch("/api/stats", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      update(data);
    } catch (err) {
      console.warn("Failed to fetch stats:", err);
    } finally {
      inFlight = false;
    }
  }

  document.getElementById("refresh-btn").addEventListener("click", poll);

  poll();
  setInterval(poll, POLL_INTERVAL_MS);
})();
