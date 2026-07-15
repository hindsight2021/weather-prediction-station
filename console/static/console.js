/* Kingsclear Atmospheric Intelligence console: polls /api/state, renders panels. */
"use strict";

const C = {
  storm: "#c97e2e", rain: "#4189c9", wind: "#7a9440",
  heat: "#cf5f3a", cold: "#2aa48d", lightning: "#c9a227",
  sand: "#d8c3a5", lilacish: "#8fa6b3",
};

const SERIES_1H = [
  { key: "storm_risk_1h",     name: "Storm",     color: C.storm },
  { key: "rain_risk_1h",      name: "Rain",      color: C.rain },
  { key: "wind_risk_1h",      name: "Wind",      color: C.wind },
  { key: "lightning_risk_1h", name: "Lightning", color: C.lightning },
];
const SERIES_24H = [
  { key: "storm_risk_24h", name: "Storm", color: C.storm },
  { key: "rain_risk_24h",  name: "Rain",  color: C.rain },
  { key: "wind_risk_24h",  name: "Wind",  color: C.wind },
  { key: "heat_risk_24h",  name: "Heat",  color: C.heat },
  { key: "cold_risk_24h",  name: "Cold",  color: C.cold },
];
const TREND_SERIES = [
  { key: "storm_risk_1h", name: "STORM", color: C.storm },
  { key: "rain_risk_1h",  name: "RAIN",  color: C.rain },
  { key: "wind_risk_1h",  name: "WIND",  color: C.wind },
  { key: "heat_risk_24h", name: "HEAT",  color: C.heat },
];
const ENV_FIELDS = [
  { key: "temperature_c",  name: "TEMPERATURE", unit: "°C" },
  { key: "humidex",        name: "HUMIDEX",     unit: "" },
  { key: "pressure_hpa",   name: "PRESSURE",    unit: "hPa" },
  { key: "wind_gust_kmh",  name: "WIND GUST",   unit: "km/h" },
  { key: "rain_rate_mm_h", name: "RAIN RATE",   unit: "mm/h" },
];

const $ = (id) => document.getElementById(id);
let lastState = null;

/* ---------- clocks ---------- */
function tick() {
  const now = new Date();
  $("clock").textContent = now.toLocaleTimeString("en-CA", { hour12: false });
  $("clock-utc").textContent = now.toLocaleTimeString("en-CA", { hour12: false, timeZone: "UTC" });
}
setInterval(tick, 1000); tick();

/* ---------- confidence gauge ---------- */
function renderGauge(value) {
  const svg = $("confidence-gauge");
  const cx = 60, cy = 60, r = 48;
  // Arc runs 270° clockwise from bottom-left, leaving the gap centered at the bottom.
  const start = 225, sweepMax = 270;
  const arc = (from, to, color, width, opacity = 1) => {
    const a0 = ((from - 90) * Math.PI) / 180, a1 = ((to - 90) * Math.PI) / 180;
    const large = to - from > 180 ? 1 : 0;
    return `<path d="M${cx + r * Math.cos(a0)},${cy + r * Math.sin(a0)} A${r},${r} 0 ${large} 1 ${cx + r * Math.cos(a1)},${cy + r * Math.sin(a1)}"
      fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" opacity="${opacity}"/>`;
  };
  let html = arc(start, start + sweepMax, "#1a252c", 9);
  if (value != null) {
    const sweep = Math.max(2, (value / 100) * sweepMax);
    const color = value >= 75 ? C.cold : value >= 45 ? C.lightning : C.heat;
    html += arc(start, start + sweep, color, 9);
  }
  svg.innerHTML = html;
  $("confidence").textContent = value != null ? value : "—";
}

/* ---------- hazards ---------- */
function renderHazards(containerId, series, prediction) {
  const container = $(containerId);
  container.innerHTML = "";
  for (const s of series) {
    const value = Math.max(0, Math.min(100, Number(prediction?.[s.key] ?? 0)));
    const row = document.createElement("div");
    row.className = "hz-row";
    row.innerHTML =
      `<span class="hz-name">${s.name}</span>` +
      `<div class="hz-track"><div class="hz-fill" style="width:${value}%;background:${s.color}"></div></div>` +
      `<span class="hz-val">${value}</span>`;
    container.appendChild(row);
  }
}

/* ---------- sensors ---------- */
function renderEnv(prediction, history) {
  const grid = $("env-grid");
  grid.innerHTML = "";
  const env = history?.environment || [];
  const latest = env.length ? env[env.length - 1] : {};
  const threeHoursAgo = env.find((p) => new Date(p.t) >= new Date(Date.now() - 3.25 * 36e5));
  for (const f of ENV_FIELDS) {
    const value = latest?.[f.key];
    const cell = document.createElement("div");
    cell.className = "env-cell";
    let deltaHtml = "";
    if (f.key === "pressure_hpa" && value != null && threeHoursAgo?.[f.key] != null) {
      const delta = value - threeHoursAgo[f.key];
      const cls = delta > 0.3 ? "rising" : delta < -0.3 ? "falling" : "";
      deltaHtml = `<span class="delta ${cls}">${delta >= 0 ? "↑" : "↓"} ${Math.abs(delta).toFixed(1)} over 3 h</span>`;
    }
    cell.innerHTML =
      `<span class="micro">${f.name}</span>` +
      `<span class="value">${value == null ? "——" : Number(value).toFixed(1)}<span class="unit">${f.unit}</span></span>` +
      deltaHtml;
    grid.appendChild(cell);
  }
}

/* ---------- status ---------- */
function renderStatus(state) {
  const p = state.prediction || {};
  const card = $("alert-card");
  card.className = "card " + ({ normal: "level-normal", advisory: "level-advisory", watch: "level-watch", warning: "level-warning" }[p.level] || "level-normal");
  $("alert-level").textContent = p.level || "standby";
  renderGauge(p.confidence != null ? Number(p.confidence) : null);
  $("explanation").textContent = p.explanation || "Awaiting telemetry…";
  const official = p.official_alert_summary || p.official_alert_level;
  $("official-alert").textContent = official && official !== "none" ? "ECCC · " + official : "ECCC · no active alerts";

  const online = state.availability === "online";
  $("link-chip").className = "chip " + (online ? "chip-up" : "chip-down");
  $("link-label").textContent = online ? "LINK UP" : "LINK DOWN";

  const imminent = $("imminent");
  if (p.imminent_event && p.imminent_event !== "none" && p.imminent_minutes >= 0) {
    imminent.classList.remove("hidden");
    $("imminent-text").textContent = p.imminent_summary || p.imminent_event;
    $("imminent-eta").textContent = p.imminent_minutes === 0 ? "now" : "T−" + p.imminent_minutes + " min";
  } else {
    imminent.classList.add("hidden");
  }
}

/* ---------- forecast ---------- */
function renderForecast(state) {
  const ai = state.ai_forecast;
  if (!ai) return;
  $("forecast-text").textContent = ai.forecast || ai.text || "";
  const at = ai.generated_at ? new Date(ai.generated_at) : null;
  $("forecast-meta").textContent =
    "filed " + (at ? at.toLocaleString("en-CA", { hour12: false }) : "—") +
    (ai.model ? " · analyst: " + ai.model : "") + " · valid 24–72 h";
}

/* ---------- verification ---------- */
function fmt(x, digits = 3) { return x == null ? "—" : Number(x).toFixed(digits); }

function renderVerification(state) {
  const body = $("verify-body");
  const rows = (state.verification?.hazards || []).filter((h) => h.n > 0);
  if (!rows.length) {
    body.textContent = "Calibration in progress — the scoreboard needs ~14 days of live telemetry before skill scores mean anything.";
    return;
  }
  let html = `<table class="verify-table"><tr><th>hazard</th><th>n</th><th>brier</th><th>climatology</th><th>skill</th><th>pod</th><th>far</th></tr>`;
  for (const h of rows) {
    const skill = h.brier_skill_vs_climatology;
    const cls = skill == null ? "" : skill > 0 ? "good" : "bad";
    html += `<tr><td>${h.hazard}</td><td>${h.n}</td><td>${fmt(h.brier)}</td>` +
      `<td>${fmt(h.brier_climatology)}</td><td class="${cls}">${fmt(skill, 2)}</td>` +
      `<td>${fmt(h.advisory_tier?.pod, 2)}</td><td>${fmt(h.advisory_tier?.far, 2)}</td></tr>`;
  }
  body.innerHTML = html + "</table>";
}

/* ---------- SVG line charts ---------- */
function drawChart(svgId, tipId, points, seriesDefs, yMax) {
  const svg = $(svgId);
  const W = svg.clientWidth || 800, H = svg.clientHeight || 180;
  const M = { l: 36, r: 78, t: 12, b: 22 };
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = "";
  if (!points || points.length < 2) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" fill="#5c6f6a" font-size="12" letter-spacing="2" text-anchor="middle" font-family="IBM Plex Mono,monospace">AWAITING TELEMETRY HISTORY</text>`;
    return;
  }
  const times = points.map((p) => new Date(p.t).getTime());
  const t0 = Math.min(...times), t1 = Math.max(...times);
  const x = (t) => M.l + ((t - t0) / Math.max(1, t1 - t0)) * (W - M.l - M.r);
  let lo = 0, hi = yMax;
  if (yMax == null) {
    const all = [];
    for (const p of points) for (const s of seriesDefs) if (p[s.key] != null) all.push(p[s.key]);
    if (!all.length) return;
    lo = Math.min(...all); hi = Math.max(...all);
    const pad = Math.max(0.5, (hi - lo) * 0.12); lo -= pad; hi += pad;
  }
  const y = (v) => H - M.b - ((v - lo) / Math.max(1e-9, hi - lo)) * (H - M.t - M.b);

  let grid = "";
  for (let i = 0; i <= 4; i++) {
    const gy = M.t + (i * (H - M.t - M.b)) / 4;
    const val = hi - (i * (hi - lo)) / 4;
    grid += `<line x1="${M.l}" x2="${W - M.r}" y1="${gy}" y2="${gy}" stroke="#16212876" stroke-width="1"/>`;
    grid += `<text x="${M.l - 7}" y="${gy + 4}" fill="#4c5d58" font-size="10" text-anchor="end" font-family="IBM Plex Mono,monospace">${Math.round(val)}</text>`;
  }
  for (let t = Math.ceil(t0 / 216e5) * 216e5; t <= t1; t += 216e5) {
    grid += `<text x="${x(t)}" y="${H - 6}" fill="#4c5d58" font-size="10" text-anchor="middle" font-family="IBM Plex Mono,monospace">${new Date(t).toLocaleTimeString("en-CA", { hour: "2-digit", minute: "2-digit", hour12: false })}</text>`;
  }
  svg.innerHTML = grid;

  for (const s of seriesDefs) {
    const path = points
      .filter((p) => p[s.key] != null)
      .map((p, i) => `${i ? "L" : "M"}${x(new Date(p.t).getTime()).toFixed(1)},${y(p[s.key]).toFixed(1)}`)
      .join(" ");
    if (!path) continue;
    svg.innerHTML += `<path d="${path}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" opacity=".95"/>`;
    const lastPoint = [...points].reverse().find((p) => p[s.key] != null);
    if (lastPoint) {
      const lx = x(new Date(lastPoint.t).getTime()), ly = y(lastPoint[s.key]);
      svg.innerHTML += `<circle cx="${lx}" cy="${ly}" r="3.2" fill="${s.color}" stroke="#0b1114" stroke-width="2"/>` +
        `<text x="${lx + 8}" y="${ly + 4}" fill="${s.color}" font-size="10.5" letter-spacing="1.2" font-family="IBM Plex Mono,monospace">${s.name}</text>`;
    }
  }

  const tip = $(tipId);
  svg.onmousemove = (ev) => {
    const rect = svg.getBoundingClientRect();
    const mx = ((ev.clientX - rect.left) / rect.width) * W;
    const t = t0 + ((mx - M.l) / Math.max(1, W - M.l - M.r)) * (t1 - t0);
    let best = points[0], bd = Infinity;
    for (const p of points) {
      const d = Math.abs(new Date(p.t).getTime() - t);
      if (d < bd) { bd = d; best = p; }
    }
    const bx = x(new Date(best.t).getTime());
    let cross = svg.querySelector("#crosshair");
    if (!cross) {
      cross = document.createElementNS("http://www.w3.org/2000/svg", "line");
      cross.id = "crosshair";
      cross.setAttribute("stroke", "#2c3e46"); cross.setAttribute("stroke-width", "1");
      svg.appendChild(cross);
    }
    cross.setAttribute("x1", bx); cross.setAttribute("x2", bx);
    cross.setAttribute("y1", M.t); cross.setAttribute("y2", H - M.b);
    let rows = "";
    for (const s of seriesDefs) if (best[s.key] != null)
      rows += `<div class="tip-row"><span style="color:${s.color}">${s.name}</span><b>${Number(best[s.key]).toFixed(1)}</b></div>`;
    tip.innerHTML = `<div class="tip-t">${new Date(best.t).toLocaleString("en-CA", { hour12: false })}</div>` + rows;
    tip.classList.remove("hidden");
    const wrapRect = svg.parentElement.getBoundingClientRect();
    const px = ev.clientX - wrapRect.left;
    tip.style.left = Math.min(px + 16, wrapRect.width - 180) + "px";
    tip.style.top = "10px";
  };
  svg.onmouseleave = () => { tip.classList.add("hidden"); svg.querySelector("#crosshair")?.remove(); };
}

function renderLegend() {
  $("trend-legend").innerHTML = TREND_SERIES
    .map((s) => `<span class="chip-l"><span class="swatch" style="background:${s.color}"></span>${s.name}</span>`)
    .join("");
}

/* ---------- polling ---------- */
async function refresh() {
  try {
    const res = await fetch("/api/state");
    const state = await res.json();
    lastState = state;
    renderStatus(state);
    renderHazards("hazards-1h", SERIES_1H, state.prediction);
    renderHazards("hazards-24h", SERIES_24H, state.prediction);
    renderEnv(state.prediction, state.history);
    drawChart("trend-svg", "trend-tip", state.history?.risks, TREND_SERIES, 100);
    // One measure per axis: pressure and temperature live on separate charts.
    drawChart("pressure-svg", "pressure-tip", state.history?.environment,
      [{ key: "pressure_hpa", name: "hPa", color: "#8fa6b3" }], null);
    drawChart("temp-svg", "temp-tip", state.history?.environment,
      [{ key: "temperature_c", name: "TEMP", color: C.sand }, { key: "humidex", name: "HUMIDEX", color: C.heat }], null);
    renderForecast(state);
    renderVerification(state);
    $("last-update").textContent = "SYNCED " + new Date().toLocaleTimeString("en-CA", { hour12: false });
  } catch (err) {
    $("link-chip").className = "chip chip-down";
    $("link-label").textContent = "LINK DOWN";
  }
}
renderLegend();
refresh();
setInterval(refresh, 30000);
window.addEventListener("resize", () => { if (lastState) refresh(); });
