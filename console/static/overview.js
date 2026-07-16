/* iHome Command overview: weather brain (MQTT cache) + HA entities via the
   console backend. Fixed one-page layout for the 9.7" iPad in landscape. */
"use strict";

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const HOME = { lat: 45.9636, lon: -66.6431 };

/* ---------- theme ---------- */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("kcr-theme", theme);
  $("theme-toggle").textContent = theme === "dark" ? "◐" : "◑";
}
$("theme-toggle").onclick = () =>
  applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
$("theme-toggle").textContent =
  document.documentElement.getAttribute("data-theme") === "dark" ? "◐" : "◑";

/* ---------- clock ---------- */
function tick() {
  const now = new Date();
  $("ov-time").textContent = now.toLocaleTimeString("en-CA", { hour: "2-digit", minute: "2-digit", hour12: false });
  $("ov-date").textContent = now.toLocaleDateString("en-CA", { weekday: "long", month: "long", day: "numeric" });
}
setInterval(tick, 5000); tick();

/* ---------- tiny scene (reuses console visual language) ---------- */
function solarNight() {
  const h = new Date().getHours();
  return h < 5 || h >= 21;
}
const cloudPath = (x, y, s) =>
  `<g transform="translate(${x},${y}) scale(${s})"><path d="M0 22 a14 14 0 0 1 13-20 a17 17 0 0 1 31 3 a12 12 0 0 1 8 17 z"/></g>`;

function sceneFor(state) {
  const p = state.prediction || {};
  const env = state.history?.environment || [];
  const latest = env.length ? env[env.length - 1] : {};
  const night = solarNight();
  const rain = latest.rain_rate_mm_h ?? 0;
  let key = night ? "clearnight" : "clear", name = night ? "clear night" : "clear skies";
  if (p.lightning_risk_1h >= 55 || p.storm_risk_1h >= 65) { key = "storm"; name = "thunderstorm conditions"; }
  else if (rain > 0.2) { key = "rain"; name = "rain"; }
  else if (p.rain_risk_1h >= 70) { key = "showers"; name = "showers nearby"; }
  else if ((latest.humidity_pct ?? 0) >= 88) { key = "cloudy"; name = "overcast"; }
  else if ((latest.humidity_pct ?? 0) >= 72) { key = "partly"; name = "partly cloudy"; }

  const sunColor = night ? "#d9dfeb" : "#f2b53c";
  const cloudFill = night ? "#5a6478cc" : "#ffffffd9";
  let svg = "";
  if (night)
    for (let i = 0; i < 9; i++)
      svg += `<circle class="star" cx="${(i * 61) % 290 + 5}" cy="${(i * 37) % 70 + 6}" r="${(i % 3) * 0.5 + 0.8}" fill="#dfe6f2" style="animation-delay:${i * 0.4}s"/>`;
  const sun = night
    ? `<circle cx="248" cy="34" r="15" fill="${sunColor}"/><circle cx="254" cy="30" r="13" fill="#37415a" opacity=".9"/>`
    : `<g class="sun-rays" style="transform-origin:248px 34px">${Array.from({ length: 8 }, (_, i) =>
        `<line x1="248" y1="12" x2="248" y2="5" stroke="${sunColor}" stroke-width="2.4" stroke-linecap="round" transform="rotate(${i * 45} 248 34)"/>`).join("")}</g>
       <circle class="sun-core" cx="248" cy="34" r="14" fill="${sunColor}"/>`;
  switch (key) {
    case "clear": case "clearnight": svg += sun; break;
    case "partly": svg += sun + `<g class="cloud-a" fill="${cloudFill}">${cloudPath(206, 32, 0.85)}</g>`; break;
    case "cloudy": svg += `<g class="cloud-a" fill="${cloudFill}">${cloudPath(196, 24, 1.0)}</g><g class="cloud-b" fill="${cloudFill}">${cloudPath(236, 44, 0.75)}</g>`; break;
    case "showers": case "rain":
      svg += `<g class="cloud-a" fill="${night ? "#454e60cc" : "#c9d2d8e6"}">${cloudPath(206, 18, 1.0)}</g>`;
      for (let i = 0; i < 6; i++)
        svg += `<line class="raindrop" x1="${216 + i * 11}" y1="52" x2="${212 + i * 11}" y2="64" stroke="var(--blue)" stroke-width="2" stroke-linecap="round" style="animation-delay:${(i % 3) * 0.3}s"/>`;
      break;
    case "storm":
      svg += `<g class="cloud-a" fill="${night ? "#3a4152" : "#8d99a3"}">${cloudPath(200, 14, 1.05)}</g>` +
        `<path class="bolt" d="M244 44 L232 66 L242 66 L229 92 L254 60 L242 60 L252 44 Z" fill="var(--gold)"/>`;
      break;
  }
  return { svg, name, night, temp: latest.temperature_c, humidex: latest.humidex };
}

/* ---------- weather brain side ---------- */
function renderWeather(state) {
  const p = state.prediction || {};
  const alertEl = $("ov-alert");
  alertEl.className = "ov-alert " + ({ normal: "level-normal", advisory: "level-advisory", watch: "level-watch", warning: "level-warning" }[p.level] || "level-normal");
  $("ov-alert-word").textContent = p.level || "standby";

  const imminent = $("ov-imminent");
  if (p.imminent_event && p.imminent_event !== "none" && p.imminent_minutes >= 0) {
    imminent.classList.remove("hidden");
    $("ov-imminent-text").textContent = p.imminent_summary || p.imminent_event;
  } else imminent.classList.add("hidden");

  const scene = sceneFor(state);
  $("ov-scene").classList.toggle("night", scene.night);
  $("ov-scene-svg").innerHTML = scene.svg;
  $("ov-temp").textContent = scene.temp != null ? Number(scene.temp).toFixed(1) + "°" : "—°";
  $("ov-cond").textContent = scene.name;
  $("ov-cond-sub").textContent =
    scene.humidex != null && scene.humidex > (scene.temp ?? 99) ? "FEELS " + Number(scene.humidex).toFixed(0) : "";

  const P = { storm: css("--amber"), rain: css("--blue"), wind: css("--olive"), heat: css("--coral"), cold: css("--teal") };
  const bars = [
    ["Storm", p.storm_risk_24h, P.storm], ["Rain", p.rain_risk_24h, P.rain],
    ["Wind", p.wind_risk_24h, P.wind], ["Heat", p.heat_risk_24h, P.heat], ["Cold", p.cold_risk_24h, P.cold],
  ];
  $("ov-risk-bars").innerHTML = bars.map(([name, v, color]) => {
    const value = Math.max(0, Math.min(100, Number(v ?? 0)));
    return `<div class="hz-row"><span class="hz-name">${name}</span>` +
      `<div class="hz-track"><div class="hz-fill" style="width:${value}%;background:${color}"></div></div>` +
      `<span class="hz-val">${value}</span></div>`;
  }).join("");

  const ai = state.ai_forecast;
  if (ai?.forecast) {
    const text = ai.forecast.replace(/^SYNOPSIS:\s*/i, "").split(/\n\nNEXT 24H:/i)[0];
    $("ov-outlook-text").textContent = text;
    if (ai.generated_at)
      $("ov-outlook-when").textContent = "· " + new Date(ai.generated_at).toLocaleTimeString("en-CA", { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  const burn = { no_burn: ["NO BURNING", "var(--coral)"], restricted_20h_to_08h: ["EVE BURNS", "var(--gold)"], burn_permitted: ["BURN OK", "var(--good)"] }[p.nb_burn_status] || ["—", "var(--ink-mute)"];
  const aqhi = p.aqhi_current;
  const aqhiColor = aqhi >= 7 ? "var(--coral)" : aqhi >= 4 ? "var(--gold)" : "var(--good)";
  $("ov-firewx").innerHTML =
    `<div class="fcell"><span class="micro">FIRE STATUS</span><span class="fval" style="color:${burn[1]}">${burn[0]}</span></div>` +
    `<div class="fcell"><span class="micro">FIRES ≤150 KM</span><span class="fval">${p.active_fires_nearby ?? "—"} · ${p.nearest_fire_km != null && p.nearest_fire_km < 900 ? p.nearest_fire_km + " km" : "—"}</span></div>` +
    `<div class="fcell"><span class="micro">AQHI</span><span class="fval" style="color:${aqhiColor}">${aqhi ?? "—"}</span></div>` +
    `<div class="fcell"><span class="micro">CONFIDENCE</span><span class="fval">${p.confidence ?? "—"}%</span></div>`;

  const env = state.history?.environment || [];
  const latest = env.length ? env[env.length - 1] : {};
  const chips = [
    ["💧", "HUMIDITY", latest.humidity_pct != null ? Number(latest.humidity_pct).toFixed(0) + "%" : "—"],
    ["🌡", "HUMIDEX", latest.humidex != null ? Number(latest.humidex).toFixed(0) : "—"],
    ["🧭", "PRESSURE", latest.pressure_hpa != null ? Number(latest.pressure_hpa).toFixed(0) : "—"],
    ["💨", "GUST", latest.wind_gust_kmh != null ? Number(latest.wind_gust_kmh).toFixed(0) + " km/h" : "—"],
    ["🌧", "RAIN", latest.rain_rate_mm_h != null ? Number(latest.rain_rate_mm_h).toFixed(1) + " mm/h" : "—"],
  ];
  $("ov-envchips").innerHTML = chips.map(([icon, label, value]) =>
    `<span class="ov-chip"><span class="ci">${icon}</span><span class="micro">${label}</span><b>${value}</b></span>`).join("");
}

/* ---------- HA side ---------- */
let haData = null;
const st = (entity) => haData?.states?.[entity]?.state;
const attr = (entity, name) => haData?.states?.[entity]?.attributes?.[name];

function renderHa() {
  if (!haData) return;
  // persons
  const persons = [
    ["Mike", "🤠", st("device_tracker.mikes_iphone")],
    ["Chris", "👨‍🍳", st("device_tracker.chris_iphone")],
  ];
  $("ov-persons").innerHTML = persons.map(([name, emoji, state]) =>
    `<span class="ov-person ${state === "home" ? "home" : ""}"><span class="p-dot">${emoji}</span>${name}${state === "home" ? "" : " · " + (state || "?")}</span>`).join("");

  // security button
  const armed = st("input_boolean.enhanced_security") === "on";
  const sec = $("ov-security");
  sec.className = "ov-sec" + (armed ? " armed" : "");
  sec.onclick = async () => {
    await fetch("/api/ha/service", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domain: "input_boolean", service: "toggle", data: { entity_id: "input_boolean.enhanced_security" } }),
    });
    setTimeout(refreshHa, 800);
  };

  // climate rows
  const acs = [
    ["Main", "climate.main_floor_ac", "sensor.average_main_floor_temp"],
    ["Bed", "climate.bedroom_ac", "sensor.average_bedroom_temperature"],
    ["Bsmt", "climate.basement_ac", "sensor.average_basement_temp"],
  ];
  $("ov-ac").innerHTML = acs.map(([name, entity, roomSensor]) => {
    const mode = st(entity) || "—";
    const target = attr(entity, "temperature");
    const room = st(roomSensor);
    return `<div class="ov-ac-row">
      <div><div class="ov-ac-name">${name}</div><div class="ov-ac-state">${mode}</div></div>
      <div class="ov-ac-cur">${room && room !== "unknown" && room !== "unavailable" ? Number(room).toFixed(1) + "°" : "—"}</div>
      <div class="ov-ac-ctl">
        <button class="ov-ac-btn" data-e="${entity}" data-d="-1">−</button>
        <span class="ov-ac-target">${target != null ? Math.round(target) : "—"}</span>
        <button class="ov-ac-btn" data-e="${entity}" data-d="1">+</button>
      </div></div>`;
  }).join("");
  for (const btn of document.querySelectorAll(".ov-ac-btn")) {
    btn.onclick = async () => {
      const entity = btn.dataset.e;
      const current = attr(entity, "temperature");
      if (current == null) return;
      await fetch("/api/ha/service", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain: "climate", service: "set_temperature",
          data: { entity_id: entity, temperature: Math.round(current) + Number(btn.dataset.d) } }),
      });
      setTimeout(refreshHa, 900);
    };
  }

  // agenda
  const events = haData.events || [];
  $("ov-events").innerHTML = events.length
    ? events.slice(0, 4).map((event) => {
        const when = new Date(event.start);
        const label = event.all_day
          ? when.toLocaleDateString("en-CA", { weekday: "short" })
          : when.toLocaleDateString("en-CA", { weekday: "short" }) + " " + when.toLocaleTimeString("en-CA", { hour: "2-digit", minute: "2-digit", hour12: false });
        return `<div class="ov-event"><span class="e-when">${label}</span><span class="e-what">${event.summary || "…"}</span></div>`;
      }).join("")
    : `<div class="ov-empty">Nothing on the calendar this week.</div>`;

  // house chips
  const mail = (entity) => { const v = st(entity); return v == null || v === "unknown" || v === "unavailable" ? "0" : v; };
  const chips = [
    ["📦", "MAIL", `${mail("sensor.mail_amazon_packages_delivered")}·${mail("sensor.mail_intelcom_delivered")}·${mail("sensor.mail_canada_post_delivered")}`],
    ["⛽", "GAS", (() => { const v = st("sensor.gas_station_regular_gas"); return v && v !== "unavailable" && v !== "unknown" ? v : "—"; })()],
    ["📶", "NET", `↓${Math.round(st("sensor.speedtest_download") || 0)} ↑${Math.round(st("sensor.speedtest_upload") || 0)}`],
    ["₿", "BTC", st("sensor.exchange_rate_1_btc") ? Number(st("sensor.exchange_rate_1_btc")).toLocaleString("en-CA", { maximumFractionDigits: 0 }) : "—"],
  ];
  $("ov-housechips").innerHTML = chips.map(([icon, label, value]) =>
    `<span class="ov-chip"><span class="ci">${icon}</span><span class="micro">${label}</span><b>${value}</b></span>`).join("");
}

/* ---------- cameras ---------- */
const CAMS = [["door", "Door"], ["drive", "Drive"], ["yard", "Yard"]];
let activeCam = 0, camAuto = true;
function renderCamTabs() {
  $("ov-cam-tabs").innerHTML = CAMS.map(([key, label], index) =>
    `<button class="ov-cam-tab ${index === activeCam ? "active" : ""}" data-i="${index}">${label}</button>`).join("");
  for (const tab of document.querySelectorAll(".ov-cam-tab"))
    tab.onclick = () => { activeCam = Number(tab.dataset.i); camAuto = false; showCam(); };
}
function showCam() {
  renderCamTabs();
  $("ov-cam-img").src = `/api/ha/camera/${CAMS[activeCam][0]}?t=${Date.now()}`;
}
setInterval(() => { if (camAuto) { activeCam = (activeCam + 1) % CAMS.length; showCam(); } }, 12000);

/* ---------- portrait refresh (daily image; re-check every 10 min) ---------- */
setInterval(() => { $("ov-portrait-img").src = `/api/ha/camera/portrait?t=${Date.now()}`; }, 600000);

/* ---------- polling ---------- */
async function refreshWeather() {
  try {
    const state = await (await fetch("/api/state")).json();
    renderWeather(state);
  } catch { /* keep last render */ }
}
async function refreshHa() {
  try {
    const data = await (await fetch("/api/ha/overview")).json();
    if (!data.error) { haData = data; renderHa(); }
  } catch { /* keep last render */ }
}
refreshWeather(); refreshHa(); showCam();
setInterval(refreshWeather, 30000);
setInterval(refreshHa, 60000);
