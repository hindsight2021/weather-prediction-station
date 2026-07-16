/* Kingsclear Atmospheric Intelligence console v2. */
"use strict";

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const HOME = { lat: 45.9636, lon: -66.6431 };
let lastState = null;

/* ---------- theme ---------- */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("kcr-theme", theme);
  $("theme-toggle").textContent = theme === "dark" ? "◐" : "◑";
  if (lastState) render(lastState); // re-resolve palette-derived colors
}
$("theme-toggle").onclick = () =>
  applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
$("theme-toggle").textContent =
  document.documentElement.getAttribute("data-theme") === "dark" ? "◐" : "◑";

/* ---------- palette (resolved live so themes swap correctly) ---------- */
function palette() {
  return {
    storm: css("--amber"), rain: css("--blue"), wind: css("--olive"),
    heat: css("--coral"), cold: css("--teal"), lightning: css("--gold"),
    sand: css("--sand"), ink2: css("--ink-2"), inkMute: css("--ink-mute"),
    line: css("--line"), coral: css("--coral"), teal: css("--teal"),
    gold: css("--gold"), good: css("--good"), blue: css("--blue"),
  };
}

/* ---------- clocks ---------- */
function tick() {
  const now = new Date();
  $("clock").textContent = now.toLocaleTimeString("en-CA", { hour12: false });
  $("clock-utc").textContent = now.toLocaleTimeString("en-CA", { hour12: false, timeZone: "UTC" });
}
setInterval(tick, 1000); tick();

/* ---------- solar calculations (NOAA approximation) ---------- */
function solarTimes(date, lat, lon) {
  const rad = Math.PI / 180;
  const dayOfYear = Math.floor((date - new Date(date.getFullYear(), 0, 0)) / 864e5);
  const gamma = (2 * Math.PI / 365) * (dayOfYear - 1 + (date.getHours() - 12) / 24);
  const eqTime = 229.18 * (0.000075 + 0.001868 * Math.cos(gamma) - 0.032077 * Math.sin(gamma)
    - 0.014615 * Math.cos(2 * gamma) - 0.040849 * Math.sin(2 * gamma));
  const decl = 0.006918 - 0.399912 * Math.cos(gamma) + 0.070257 * Math.sin(gamma)
    - 0.006758 * Math.cos(2 * gamma) + 0.000907 * Math.sin(2 * gamma)
    - 0.002697 * Math.cos(3 * gamma) + 0.00148 * Math.sin(3 * gamma);
  const haCos = (Math.cos(90.833 * rad) / (Math.cos(lat * rad) * Math.cos(decl))) - Math.tan(lat * rad) * Math.tan(decl);
  if (haCos < -1 || haCos > 1) return null; // polar day/night — not in NB
  const ha = Math.acos(haCos) / rad;
  const solarNoonMin = 720 - 4 * lon - eqTime; // minutes UTC
  const offsetMin = -date.getTimezoneOffset();
  const sunrise = new Date(date); sunrise.setHours(0, 0, 0, 0); sunrise.setMinutes(solarNoonMin - ha * 4 + offsetMin);
  const sunset = new Date(date); sunset.setHours(0, 0, 0, 0); sunset.setMinutes(solarNoonMin + ha * 4 + offsetMin);
  return { sunrise, sunset };
}

/* ---------- hero weather scene ---------- */
function conditionFrom(state) {
  const p = state.prediction || {};
  const inputs = state.inputs || {};
  const env = state.history?.environment || [];
  const latest = env.length ? env[env.length - 1] : {};
  const rain = latest.rain_rate_mm_h ?? 0;
  const temp = latest.temperature_c;
  const gust = latest.wind_gust_kmh ?? 0;
  const lightningKm = inputs["lightning/local/distance_km"];
  const radar = inputs["radar/nearby/precip"];
  const humidity = latest.humidity_pct ?? 0;

  const sun = solarTimes(new Date(), HOME.lat, HOME.lon);
  const now = new Date();
  const night = sun ? now < sun.sunrise || now > sun.sunset : (now.getHours() < 6 || now.getHours() >= 21);

  if ((lightningKm != null && lightningKm <= 40) || p.lightning_risk_1h >= 55 || p.storm_risk_1h >= 65)
    return { key: "storm", name: "thunderstorm conditions", night };
  if (rain > 0.2 && temp != null && temp <= 0.5) return { key: "snow", name: "snow", night };
  if (rain > 0.2) return { key: "rain", name: "rain", night };
  if (radar === 1 || p.rain_risk_1h >= 70) return { key: "showers", name: "showers nearby", night };
  if (gust >= 45) return { key: "wind", name: "windy", night };
  if (humidity >= 88) return { key: "cloudy", name: "overcast", night };
  if (humidity >= 72) return { key: "partly", name: "partly cloudy", night };
  return { key: night ? "clearnight" : "clear", name: night ? "clear night" : "clear skies", night };
}

const cloudPath = (x, y, s) =>
  `<g transform="translate(${x},${y}) scale(${s})"><path d="M0 22 a14 14 0 0 1 13-20 a17 17 0 0 1 31 3 a12 12 0 0 1 8 17 z" /></g>`;

function heroScene(cond) {
  const night = cond.night;
  const sunColor = night ? "#d9dfeb" : "#f2b53c";
  const cloudFill = night ? "#5a6478cc" : "#ffffffd9";
  const cloudDark = night ? "#454e60cc" : "#c9d2d8e6";
  let svg = "";
  if (night) {
    for (let i = 0; i < 14; i++) {
      const x = (i * 73) % 390, y = (i * 41) % 120;
      svg += `<circle class="star" cx="${x + 5}" cy="${y + 8}" r="${(i % 3) * 0.5 + 0.9}" fill="#dfe6f2" style="animation-delay:${i * 0.4}s"/>`;
    }
  }
  const sun = night
    ? `<g><circle cx="322" cy="52" r="22" fill="${sunColor}"/><circle cx="330" cy="46" r="19" fill="${night ? "var(--hero-moon-mask, #37415a)" : "#0e1c22"}" opacity=".92"/></g>`
    : `<g class="sun-rays" style="transform-origin:322px 52px">${Array.from({ length: 8 }, (_, i) =>
        `<line x1="322" y1="18" x2="322" y2="8" stroke="${sunColor}" stroke-width="3" stroke-linecap="round" transform="rotate(${i * 45} 322 52)"/>`).join("")}</g>
       <circle class="sun-core" cx="322" cy="52" r="20" fill="${sunColor}"/>`;

  switch (cond.key) {
    case "clear": case "clearnight":
      svg += sun; break;
    case "partly":
      svg += sun + `<g class="cloud-a" fill="${cloudFill}">${cloudPath(272, 48, 1.1)}</g>`; break;
    case "cloudy":
      svg += `<g class="cloud-b" fill="${cloudDark}">${cloudPath(292, 30, 1.15)}</g>` +
             `<g class="cloud-a" fill="${cloudFill}">${cloudPath(248, 48, 1.3)}</g>`; break;
    case "showers": case "rain": {
      svg += `<g class="cloud-a" fill="${cloudDark}">${cloudPath(280, 26, 1.35)}</g>`;
      for (let i = 0; i < 8; i++)
        svg += `<line class="raindrop" x1="${292 + i * 12}" y1="68" x2="${288 + i * 12}" y2="82" stroke="var(--blue)" stroke-width="2.4" stroke-linecap="round" style="animation-delay:${(i % 4) * 0.28}s"/>`;
      break;
    }
    case "storm": {
      svg += `<g class="cloud-a" fill="${night ? "#3a4152" : "#8d99a3"}">${cloudPath(272, 22, 1.4)}</g>`;
      svg += `<path class="bolt" d="M330 64 L314 94 L328 94 L310 128 L344 86 L328 86 L342 64 Z" fill="var(--gold)"/>`;
      for (let i = 0; i < 5; i++)
        svg += `<line class="raindrop" x1="${284 + i * 12}" y1="66" x2="${280 + i * 12}" y2="80" stroke="var(--blue)" stroke-width="2.2" stroke-linecap="round" style="animation-delay:${(i % 3) * 0.33}s"/>`;
      break;
    }
    case "snow": {
      svg += `<g class="cloud-a" fill="${cloudFill}">${cloudPath(280, 26, 1.35)}</g>`;
      for (let i = 0; i < 7; i++)
        svg += `<circle class="snowflake" cx="${292 + i * 13}" cy="72" r="2.4" fill="${night ? "#dfe6f2" : "#ffffff"}" style="animation-delay:${(i % 4) * 0.5}s"/>`;
      break;
    }
    case "wind": {
      svg += sun;
      for (let i = 0; i < 3; i++)
        svg += `<path class="windline" d="M180 ${105 + i * 20} q 60 ${-12 + i * 8} 130 0" fill="none" stroke="var(--olive)" stroke-width="2.6" stroke-linecap="round" style="animation-delay:${i * 0.5}s"/>`;
      break;
    }
  }
  return svg;
}

function renderHero(state) {
  const cond = conditionFrom(state);
  const scene = $("hero-scene");
  scene.classList.toggle("night", cond.night);
  $("hero-svg").innerHTML = heroScene(cond);
  const env = state.history?.environment || [];
  const latest = env.length ? env[env.length - 1] : {};
  $("hero-temp").textContent = latest.temperature_c != null ? Number(latest.temperature_c).toFixed(1) : "—";
  $("hero-cond-name").textContent = cond.name;
  const feel = latest.humidex != null && latest.humidex > (latest.temperature_c ?? 99)
    ? `feels like ${Number(latest.humidex).toFixed(0)}` : null;
  $("hero-cond-sub").textContent = [feel, `humidity ${latest.humidity_pct != null ? Number(latest.humidity_pct).toFixed(0) + "%" : "—"}`]
    .filter(Boolean).join(" · ");
  const inputs = state.inputs || {};
  const chips = [
    ["RAIN 1H", pct(inputs["ha_bridge/forecast/precip_probability_1h"])],
    ["RAIN 24H", pct(inputs["ha_bridge/forecast/precip_probability_24h"])],
    ["RAIN TODAY", inputs["ha_bridge/atlas/rain_total"] != null ? Number(inputs["ha_bridge/atlas/rain_total"]).toFixed(1) + " mm" : null],
    ["LIGHTNING", inputs["lightning/local/distance_km"] != null ? Number(inputs["lightning/local/distance_km"]).toFixed(0) + " km" : null],
  ].filter(([, v]) => v != null);
  $("hero-chips").innerHTML = chips.map(([k, v]) => `<span class="hero-chip">${k} <b>${v}</b></span>`).join("");
}
const pct = (v) => (v == null ? null : Number(v).toFixed(0) + "%");

/* ---------- confidence gauge ---------- */
function arcPath(cx, cy, r, fromDeg, toDeg) {
  const a0 = ((fromDeg - 90) * Math.PI) / 180, a1 = ((toDeg - 90) * Math.PI) / 180;
  const large = toDeg - fromDeg > 180 ? 1 : 0;
  return `M${cx + r * Math.cos(a0)},${cy + r * Math.sin(a0)} A${r},${r} 0 ${large} 1 ${cx + r * Math.cos(a1)},${cy + r * Math.sin(a1)}`;
}
function renderGauge(value) {
  const svg = $("confidence-gauge");
  const P = palette();
  const start = 225, sweepMax = 270;
  let html = `<path d="${arcPath(60, 60, 48, start, start + sweepMax)}" fill="none" stroke="${P.line}" stroke-width="9" stroke-linecap="round"/>`;
  if (value != null) {
    const sweep = Math.max(2, (value / 100) * sweepMax);
    const color = value >= 75 ? P.teal : value >= 45 ? P.gold : P.coral;
    html += `<path d="${arcPath(60, 60, 48, start, start + sweep)}" fill="none" stroke="${color}" stroke-width="9" stroke-linecap="round"/>`;
  }
  svg.innerHTML = html;
  $("confidence").textContent = value != null ? value : "—";
}

/* ---------- wind compass ---------- */
function renderCompass(state) {
  const P = palette();
  const inputs = state.inputs || {};
  const env = state.history?.environment || [];
  const latest = env.length ? env[env.length - 1] : {};
  const dir = inputs["ha_bridge/atlas/wind_direction"];
  const speed = latest.wind_speed_kmh ?? inputs["ha_bridge/atlas/wind_speed_kmh"];
  const gust = latest.wind_gust_kmh;
  const svg = $("compass");
  const cx = 65, cy = 65, r = 52;
  let html = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${P.line}" stroke-width="1.4"/>`;
  const cards = ["N", "E", "S", "W"];
  for (let i = 0; i < 360; i += 30) {
    const a = (i - 90) * Math.PI / 180;
    const isCard = i % 90 === 0;
    const r0 = isCard ? r - 9 : r - 5;
    html += `<line x1="${cx + r0 * Math.cos(a)}" y1="${cy + r0 * Math.sin(a)}" x2="${cx + r * Math.cos(a)}" y2="${cy + r * Math.sin(a)}" stroke="${P.inkMute}" stroke-width="${isCard ? 2 : 1}"/>`;
    if (isCard)
      html += `<text x="${cx + (r - 19) * Math.cos(a)}" y="${cy + (r - 19) * Math.sin(a) + 4}" fill="${P.ink2}" font-size="11" font-family="IBM Plex Mono,monospace" text-anchor="middle">${cards[i / 90]}</text>`;
  }
  if (dir != null) {
    // Needle points where the wind blows FROM.
    html += `<g transform="rotate(${Number(dir)} ${cx} ${cy})">
      <path d="M${cx} ${cy - r + 13} L${cx - 6} ${cy + 8} L${cx} ${cy + 2} L${cx + 6} ${cy + 8} Z" fill="${P.teal}"/>
    </g><circle cx="${cx}" cy="${cy}" r="4" fill="${P.sand}"/>`;
  } else {
    html += `<circle cx="${cx}" cy="${cy}" r="4" fill="${P.inkMute}"/>`;
  }
  svg.innerHTML = html;
  const compassDirName = dir != null
    ? ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"][Math.round(Number(dir) / 22.5) % 16]
    : "—";
  $("wind-dir").textContent = dir != null ? `${compassDirName} ${Number(dir).toFixed(0)}°` : "—";
  $("wind-detail").textContent =
    `${speed != null ? Number(speed).toFixed(0) : "—"} km/h · gusting ${gust != null ? Number(gust).toFixed(0) : "—"}`;
}

/* ---------- daylight arc ---------- */
function renderDaylight() {
  const P = palette();
  const now = new Date();
  const sun = solarTimes(now, HOME.lat, HOME.lon);
  const svg = $("daylight");
  if (!sun) { svg.innerHTML = ""; return; }
  const cx = 85, cy = 88, r = 66;
  let html = `<line x1="10" y1="${cy}" x2="160" y2="${cy}" stroke="${P.line}" stroke-width="1.2"/>`;
  html += `<path d="${arcPath(cx, cy, r, 270, 450)}" fill="none" stroke="${P.line}" stroke-width="2" stroke-dasharray="4 5"/>`;
  const frac = Math.min(1, Math.max(0, (now - sun.sunrise) / (sun.sunset - sun.sunrise)));
  const isDay = frac > 0 && frac < 1;
  if (isDay) {
    html += `<path d="${arcPath(cx, cy, r, 270, 270 + frac * 180)}" fill="none" stroke="${P.gold}" stroke-width="2.4"/>`;
    const a = (270 + frac * 180 - 90) * Math.PI / 180;
    html += `<circle cx="${cx + r * Math.cos(a)}" cy="${cy + r * Math.sin(a)}" r="6" fill="${P.gold}"/>`;
  }
  svg.innerHTML = html;
  const fmt = (d) => d.toLocaleTimeString("en-CA", { hour: "2-digit", minute: "2-digit", hour12: false });
  $("sun-times").textContent = `↑ ${fmt(sun.sunrise)}   ↓ ${fmt(sun.sunset)}`;
  const remaining = isDay ? Math.round((sun.sunset - now) / 6e4) : null;
  $("sun-detail").textContent = isDay
    ? `${Math.floor(remaining / 60)}h ${remaining % 60}m of daylight left`
    : "after dark — next sunrise " + fmt(sun.sunrise);
}

/* ---------- hazards ---------- */
function hazardSeries() {
  const P = palette();
  return {
    h1: [
      { key: "storm_risk_1h", name: "Storm", color: P.storm },
      { key: "rain_risk_1h", name: "Rain", color: P.rain },
      { key: "wind_risk_1h", name: "Wind", color: P.wind },
      { key: "lightning_risk_1h", name: "Lightning", color: P.lightning },
    ],
    h24: [
      { key: "storm_risk_24h", name: "Storm", color: P.storm },
      { key: "rain_risk_24h", name: "Rain", color: P.rain },
      { key: "wind_risk_24h", name: "Wind", color: P.wind },
      { key: "heat_risk_24h", name: "Heat", color: P.heat },
      { key: "cold_risk_24h", name: "Cold", color: P.cold },
      { key: "air_quality_risk_24h", name: "Air", color: P.ink2 },
    ],
  };
}
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

/* ---------- outlook ---------- */
function renderOutlook(prediction) {
  const P = palette();
  const cells = [
    ["STORM 24H", prediction?.storm_risk_24h, P.storm],
    ["STORM 48H", prediction?.storm_risk_48h, P.storm],
    ["STORM 72H", prediction?.storm_risk_72h, P.storm],
    ["AIR QUALITY 24H", prediction?.air_quality_risk_24h, P.ink2],
    ["AIR QUALITY 48H", prediction?.air_quality_risk_48h, P.ink2],
  ];
  const grid = $("outlook-grid");
  grid.innerHTML = "";
  let previous = null;
  for (const [label, value, color] of cells) {
    const v = value != null ? Number(value) : null;
    const trend = previous != null && v != null ? (v > previous + 3 ? "▲ building" : v < previous - 3 ? "▼ easing" : "— steady") : "";
    if (label.startsWith("STORM")) previous = v;
    grid.innerHTML +=
      `<div class="outlook-cell"><span class="micro">${label}</span>` +
      `<span class="big" style="color:${v != null && v >= 60 ? css("--coral") : color}">${v != null ? v + "%" : "—"}</span>` +
      `<span class="trend">${trend}</span></div>`;
  }
}

/* ---------- fire & air strip ---------- */
function burnPill(status) {
  const map = {
    no_burn: ["BURNING PROHIBITED", "pill-red"],
    restricted_20h_to_08h: ["BURN 20:00–08:00 ONLY", "pill-amber"],
    burn_permitted: ["BURNING PERMITTED", "pill-green"],
  };
  return map[status] || ["STATUS UNKNOWN", "pill-gray"];
}
function renderFireStrip(prediction) {
  const strip = $("fire-strip");
  const [burnText, burnClass] = burnPill(prediction?.nb_burn_status);
  const nearest = prediction?.nearest_fire_km;
  const aqhi = prediction?.aqhi_current;
  const aqhiColor = aqhi >= 7 ? "var(--coral)" : aqhi >= 4 ? "var(--gold)" : "var(--good)";
  strip.innerHTML = `
    <div class="fire-cell"><span class="f-icon">🔥</span><div><span class="micro">ACTIVE FIRES ≤150 KM</span><span class="f-val">${prediction?.active_fires_nearby ?? "—"}</span></div></div>
    <div class="fire-cell"><span class="f-icon">📍</span><div><span class="micro">NEAREST ACTIVE FIRE</span><span class="f-val">${nearest != null && nearest < 900 ? nearest + " km" : "none"}</span></div></div>
    <div class="fire-cell"><span class="f-icon">💨</span><div><span class="micro">SMOKE RISK</span><span class="f-val">${prediction?.smoke_risk_24h ?? "—"}%</span></div></div>
    <div class="fire-cell"><span class="f-icon">🫁</span><div><span class="micro">AQHI NOW / 24H</span><span class="f-val" style="color:${aqhiColor}">${aqhi ?? "—"} / ${prediction?.aqhi_forecast_max_24h ?? "—"}</span></div></div>
    <div class="fire-cell"><div><span class="micro">YORK COUNTY BURN STATUS</span><br><span class="status-pill ${burnClass}">${burnText}</span></div></div>`;
}

/* ---------- status / analysis ---------- */
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

  const parts = [];
  if (p.ml_status) parts.push(p.ml_status);
  if (p.model_accuracy && p.model_accuracy !== "No models trained yet") parts.push(p.model_accuracy);
  $("ml-line").textContent = parts.join(" · ");

  const imminent = $("imminent");
  if (p.imminent_event && p.imminent_event !== "none" && p.imminent_minutes >= 0) {
    imminent.classList.remove("hidden");
    $("imminent-text").textContent = p.imminent_summary || p.imminent_event;
    $("imm-min").textContent = p.imminent_minutes === 0 ? "now" : p.imminent_minutes;
    const P = palette();
    const frac = Math.max(0.03, 1 - p.imminent_minutes / 120);
    $("imm-svg").innerHTML =
      `<circle cx="20" cy="20" r="16" fill="none" stroke="${P.line}" stroke-width="3"/>` +
      `<circle cx="20" cy="20" r="16" fill="none" stroke="${P.coral}" stroke-width="3" stroke-linecap="round"
        stroke-dasharray="${(frac * 100.5).toFixed(1)} 100.5" transform="rotate(-90 20 20)"/>`;
  } else {
    imminent.classList.add("hidden");
  }
}

/* ---------- sensor tiles with sparklines ---------- */
function sparkline(values, color) {
  if (!values || values.filter((v) => v != null).length < 2) return "";
  const clean = values.map((v) => (v == null ? null : Number(v)));
  const present = clean.filter((v) => v != null);
  const lo = Math.min(...present), hi = Math.max(...present);
  const W = 110, H = 26, pad = 2;
  const y = (v) => H - pad - ((v - lo) / Math.max(1e-9, hi - lo)) * (H - pad * 2);
  const step = W / (clean.length - 1);
  const d = clean.map((v, i) => (v == null ? "" : `${i === 0 || clean[i - 1] == null ? "M" : "L"}${(i * step).toFixed(1)},${y(v).toFixed(1)}`)).join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" opacity=".8"/></svg>`;
}

function renderEnv(state) {
  const P = palette();
  const grid = $("env-grid");
  grid.innerHTML = "";
  const env = state.history?.environment || [];
  const latest = env.length ? env[env.length - 1] : {};
  const threeHoursAgo = env.find((point) => new Date(point.t) >= new Date(Date.now() - 3.25 * 36e5));
  const fields = [
    { key: "temperature_c", name: "TEMPERATURE", unit: "°C", color: P.sand },
    { key: "humidex", name: "HUMIDEX", unit: "", color: P.heat },
    { key: "humidity_pct", name: "HUMIDITY", unit: "%", color: P.rain },
    { key: "pressure_hpa", name: "PRESSURE", unit: "hPa", color: P.ink2 },
    { key: "wind_speed_kmh", name: "WIND", unit: "km/h", color: P.wind },
    { key: "wind_gust_kmh", name: "GUST", unit: "km/h", color: P.wind },
    { key: "rain_rate_mm_h", name: "RAIN RATE", unit: "mm/h", color: P.rain },
  ];
  for (const f of fields) {
    const value = latest?.[f.key];
    let deltaHtml = "";
    if (f.key === "pressure_hpa" && value != null && threeHoursAgo?.[f.key] != null) {
      const delta = value - threeHoursAgo[f.key];
      const cls = delta > 0.3 ? "rising" : delta < -0.3 ? "falling" : "";
      deltaHtml = `<span class="delta ${cls}">${delta >= 0 ? "↑" : "↓"} ${Math.abs(delta).toFixed(1)} / 3 h</span>`;
    }
    const series = env.map((point) => point[f.key]);
    grid.innerHTML +=
      `<div class="env-cell"><span class="micro">${f.name}</span>` +
      `<span class="value">${value == null ? "——" : Number(value).toFixed(1)}<span class="unit">${f.unit}</span></span>` +
      deltaHtml + sparkline(series, f.color) + `</div>`;
  }
}

/* ---------- forecast + verification ---------- */
function renderForecast(state) {
  const ai = state.ai_forecast;
  if (!ai) return;
  $("forecast-text").textContent = ai.forecast || ai.text || "";
  const at = ai.generated_at ? new Date(ai.generated_at) : null;
  $("forecast-meta").textContent =
    "filed " + (at ? at.toLocaleString("en-CA", { hour12: false }) : "—") +
    (ai.model ? " · analyst: " + ai.model : "") + " · valid 24–72 h";
}

const fmt = (x, digits = 3) => (x == null ? "—" : Number(x).toFixed(digits));
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
  const P = palette();
  const svg = $(svgId);
  const W = svg.clientWidth || 800, H = svg.clientHeight || 180;
  const M = { l: 36, r: 78, t: 12, b: 22 };
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = "";
  if (!points || points.length < 2) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" fill="${P.inkMute}" font-size="12" letter-spacing="2" text-anchor="middle" font-family="IBM Plex Mono,monospace">AWAITING TELEMETRY HISTORY</text>`;
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
    grid += `<line x1="${M.l}" x2="${W - M.r}" y1="${gy}" y2="${gy}" stroke="${P.line}" stroke-width="1" opacity=".5"/>`;
    grid += `<text x="${M.l - 7}" y="${gy + 4}" fill="${P.inkMute}" font-size="10" text-anchor="end" font-family="IBM Plex Mono,monospace">${Math.round(val)}</text>`;
  }
  for (let t = Math.ceil(t0 / 216e5) * 216e5; t <= t1; t += 216e5) {
    grid += `<text x="${x(t)}" y="${H - 6}" fill="${P.inkMute}" font-size="10" text-anchor="middle" font-family="IBM Plex Mono,monospace">${new Date(t).toLocaleTimeString("en-CA", { hour: "2-digit", minute: "2-digit", hour12: false })}</text>`;
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
      svg.innerHTML += `<circle cx="${lx}" cy="${ly}" r="3.2" fill="${s.color}" stroke="${css("--bg")}" stroke-width="2"/>` +
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
    let cross = svg.querySelector(".crosshair");
    if (!cross) {
      cross = document.createElementNS("http://www.w3.org/2000/svg", "line");
      cross.setAttribute("class", "crosshair");
      cross.setAttribute("stroke", P.inkMute); cross.setAttribute("stroke-width", "1");
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
    tip.style.left = Math.min(ev.clientX - wrapRect.left + 16, wrapRect.width - 180) + "px";
    tip.style.top = "10px";
  };
  svg.onmouseleave = () => { tip.classList.add("hidden"); svg.querySelector(".crosshair")?.remove(); };
}

function renderLegend() {
  const P = palette();
  const series = [
    { name: "STORM", color: P.storm }, { name: "RAIN", color: P.rain },
    { name: "WIND", color: P.wind }, { name: "HEAT", color: P.heat },
    { name: "CONFIDENCE", color: P.inkMute },
  ];
  $("trend-legend").innerHTML = series
    .map((s) => `<span class="chip-l"><span class="swatch" style="background:${s.color}"></span>${s.name}</span>`)
    .join("");
}

/* ---------- render all ---------- */
function render(state) {
  const P = palette();
  renderStatus(state);
  renderHero(state);
  const hz = hazardSeries();
  renderHazards("hazards-1h", hz.h1, state.prediction);
  renderHazards("hazards-24h", hz.h24, state.prediction);
  renderOutlook(state.prediction);
  renderFireStrip(state.prediction);
  renderEnv(state);
  renderCompass(state);
  renderDaylight();
  renderLegend();
  drawChart("trend-svg", "trend-tip", state.history?.risks, [
    { key: "storm_risk_1h", name: "STORM", color: P.storm },
    { key: "rain_risk_1h", name: "RAIN", color: P.rain },
    { key: "wind_risk_1h", name: "WIND", color: P.wind },
    { key: "heat_risk_24h", name: "HEAT", color: P.heat },
    { key: "confidence", name: "CONF", color: P.inkMute },
  ], 100);
  drawChart("pressure-svg", "pressure-tip", state.history?.environment,
    [{ key: "pressure_hpa", name: "hPa", color: P.ink2 }], null);
  drawChart("temp-svg", "temp-tip", state.history?.environment,
    [{ key: "temperature_c", name: "TEMP", color: P.sand }, { key: "humidex", name: "HUMIDEX", color: P.heat }], null);
  renderForecast(state);
  renderVerification(state);
  $("last-update").textContent = "SYNCED " + new Date().toLocaleTimeString("en-CA", { hour12: false });
}

async function refresh() {
  try {
    const res = await fetch("/api/state");
    const state = await res.json();
    if (state.home) { HOME.lat = state.home.lat; HOME.lon = state.home.lon; }
    lastState = state;
    render(state);
  } catch (err) {
    $("link-chip").className = "chip chip-down";
    $("link-label").textContent = "LINK DOWN";
  }
}
refresh();
setInterval(refresh, 30000);
setInterval(renderDaylight, 60000);
window.addEventListener("resize", () => { if (lastState) render(lastState); });
