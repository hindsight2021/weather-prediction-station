/* NB Fire Warden console: renders our own SVG map from GNB ERD GeoJSON. */
"use strict";

const $ = (id) => document.getElementById(id);

/* ---------- theme: auto day/night via shared engine ---------- */
KCRTheme.bind($("theme-toggle"));

function tick() {
  $("clock").textContent = new Date().toLocaleTimeString("en-CA", { hour12: false });
}
setInterval(tick, 1000); tick();

/* ---------- projection ----------
   Simple equirectangular projection fitted to the data's bounding box,
   with latitude compensation so NB isn't squashed. */
function makeProjection(bounds, width, height, pad) {
  const latMid = (bounds.minLat + bounds.maxLat) / 2;
  const kx = Math.cos((latMid * Math.PI) / 180);
  const spanX = (bounds.maxLon - bounds.minLon) * kx;
  const spanY = bounds.maxLat - bounds.minLat;
  const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY);
  return {
    x: (lon) => pad + ((lon - bounds.minLon) * kx) * scale,
    y: (lat) => height - pad - (lat - bounds.minLat) * scale,
    kmToPx: (km) => (km / 111.32) * scale, // deg latitude ≈ 111.32 km
  };
}

function geometryBounds(counties) {
  const bounds = { minLon: Infinity, maxLon: -Infinity, minLat: Infinity, maxLat: -Infinity };
  const visit = (coords) => {
    if (typeof coords[0] === "number") {
      bounds.minLon = Math.min(bounds.minLon, coords[0]);
      bounds.maxLon = Math.max(bounds.maxLon, coords[0]);
      bounds.minLat = Math.min(bounds.minLat, coords[1]);
      bounds.maxLat = Math.max(bounds.maxLat, coords[1]);
    } else coords.forEach(visit);
  };
  for (const county of counties) if (county.geometry) visit(county.geometry.coordinates);
  return bounds;
}

function ringsOf(geometry) {
  if (!geometry) return [];
  if (geometry.type === "Polygon") return geometry.coordinates;
  if (geometry.type === "MultiPolygon") return geometry.coordinates.flat();
  return [];
}

/* Decimate long rings so the SVG stays light. */
function simplify(ring, maxPoints = 220) {
  if (ring.length <= maxPoints) return ring;
  const step = Math.ceil(ring.length / maxPoints);
  return ring.filter((_, i) => i % step === 0);
}

function centroidOf(rings) {
  let sx = 0, sy = 0, n = 0;
  for (const point of rings[0] || []) { sx += point[0]; sy += point[1]; n++; }
  return n ? [sx / n, sy / n] : null;
}

/* ---------- map render ---------- */
function renderMap(data) {
  const svg = $("nb-map");
  const W = 640, H = 560, PAD = 26;
  const counties = (data.counties || []).filter((c) => c.geometry);
  if (!counties.length) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" class="map-label" font-size="13">MAP FEED UNAVAILABLE</text>`;
    return;
  }
  const proj = makeProjection(geometryBounds(counties), W, H, PAD);

  let html = "";
  for (const county of counties) {
    const d = ringsOf(county.geometry)
      .map((ring) => "M" + simplify(ring).map((pt) => `${proj.x(pt[0]).toFixed(1)},${proj.y(pt[1]).toFixed(1)}`).join("L") + "Z")
      .join(" ");
    html += `<path class="county county-${county.category}" d="${d}"><title>${county.name} — category ${county.category}</title></path>`;
    const centroid = centroidOf(ringsOf(county.geometry));
    if (centroid)
      html += `<text class="map-label" x="${proj.x(centroid[0]).toFixed(1)}" y="${proj.y(centroid[1]).toFixed(1)}" text-anchor="middle">${county.name.toUpperCase()}</text>`;
  }

  // range rings from home
  const hx = proj.x(data.home.lon), hy = proj.y(data.home.lat);
  for (const km of [50, 100, 150]) {
    html += `<circle class="range-ring" cx="${hx}" cy="${hy}" r="${proj.kmToPx(km).toFixed(1)}"/>`;
    html += `<text class="map-label" x="${hx + proj.kmToPx(km) - 4}" y="${hy - 4}" text-anchor="end">${km} KM</text>`;
  }

  // fires
  for (const fire of data.fires || []) {
    const fx = proj.x(fire.lon), fy = proj.y(fire.lat);
    const cls = { OC: "fire-oc", BH: "fire-bh", UC: "fire-uc" }[fire.stage] || "fire-ex";
    const r = fire.stage === "EX" ? 3 : 4.5;
    if (fire.stage === "OC") html += `<circle class="fire-pulse" cx="${fx}" cy="${fy}" r="7"/>`;
    html += `<circle class="fire-marker ${cls}" cx="${fx}" cy="${fy}" r="${r}"><title>${fire.name} · ${fire.stage} · ${fire.distance_km} km</title></circle>`;
  }

  // home
  html += `<path class="home-marker" transform="translate(${hx},${hy})" d="M0,-8 L2.3,-2.5 L8,-2.5 L3.4,1.2 L5.2,7 L0,3.5 L-5.2,7 L-3.4,1.2 L-8,-2.5 L-2.3,-2.5 Z"/>`;
  svg.innerHTML = html;
}

/* ---------- banner + list ---------- */
const STAGE_LABELS = { OC: "OUT OF CONTROL", BH: "BEING HELD", UC: "UNDER CONTROL", EX: "EXTINGUISHED" };
const STAGE_PILL = { OC: "pill-red", BH: "pill-amber", UC: "pill-gray", EX: "pill-gray" };

function renderBanner(data, weather) {
  const banner = $("fire-banner");
  const status = data.york_burn_status;
  const map = {
    no_burn: ["BURNING PROHIBITED", "fb-red", "Category 1 — open burning is not permitted."],
    restricted_20h_to_08h: ["EVENING BURNS ONLY", "fb-amber", "Category 2 — burning permitted 20:00–08:00 only."],
    burn_permitted: ["BURNING PERMITTED", "fb-green", "Category 3 — burning permitted; stay attentive."],
  };
  const [word, cls, sub] = map[status] || ["STATUS UNKNOWN", "fb-amber", "Burn category feed unavailable."];
  banner.className = "fire-banner " + cls;
  $("fb-word").textContent = word;
  $("fb-sub").textContent = sub + (data.stale ? " · FEED STALE — showing last good data" : "");
  $("fb-count").textContent = data.active_fire_count ?? "—";
  $("fb-nearest").textContent = data.nearest_active_km != null ? data.nearest_active_km + " km" : "none";
  const aqhi = weather?.prediction?.aqhi_current;
  $("fb-aqhi").textContent = aqhi ?? "—";
  $("fb-aqhi").style.color = aqhi >= 7 ? "var(--coral)" : aqhi >= 4 ? "var(--gold)" : "var(--good)";
}

function renderList(data) {
  const list = $("fire-list");
  // Active incidents first (by distance), extinguished afterwards.
  const fires = [...(data.fires || [])]
    .sort((a, b) => (a.stage === "EX") - (b.stage === "EX") || a.distance_km - b.distance_km)
    .slice(0, 30);
  if (!fires.length) {
    list.innerHTML = `<div class="fire-row"><span class="fr-name">No incidents in the provincial feed.</span></div>`;
    return;
  }
  list.innerHTML = fires.map((fire) => {
    const size = fire.size_ha != null ? `${Number(fire.size_ha).toFixed(1)} ha` : "size n/a";
    const date = fire.detected ? String(fire.detected).slice(0, 10) : "";
    return `<div class="fire-row">
      <span class="status-pill ${STAGE_PILL[fire.stage] || "pill-gray"}">${STAGE_LABELS[fire.stage] || fire.stage}</span>
      <div><div class="fr-name">${fire.name}</div><div class="fr-meta">${size}${date ? " · detected " + date : ""}</div></div>
      <div class="fr-dist">${fire.distance_km}<span class="u"> km</span></div>
    </div>`;
  }).join("");
}

function renderAir(weather) {
  const p = weather?.prediction || {};
  $("fire-air").innerHTML = `
    <div class="fire-cell"><span class="f-icon">💨</span><div><span class="micro">SMOKE RISK 24H</span><span class="f-val">${p.smoke_risk_24h ?? "—"}%</span></div></div>
    <div class="fire-cell"><span class="f-icon">🫁</span><div><span class="micro">AIR QUALITY RISK 24/48H</span><span class="f-val">${p.air_quality_risk_24h ?? "—"} / ${p.air_quality_risk_48h ?? "—"}%</span></div></div>
    <div class="fire-cell"><span class="f-icon">📈</span><div><span class="micro">AQHI FORECAST 24H</span><span class="f-val">${p.aqhi_forecast_max_24h ?? "—"}</span></div></div>`;
}

/* ---------- polling ---------- */
async function refresh() {
  try {
    const [fireRes, stateRes] = await Promise.all([fetch("/api/fires"), fetch("/api/state")]);
    const data = await fireRes.json();
    const weather = await stateRes.json();
    if (data.error) throw new Error(data.error);
    renderMap(data);
    renderBanner(data, weather);
    renderList(data);
    renderAir(weather);
    $("link-chip").className = "chip chip-up";
    $("link-label").textContent = data.stale ? "FEED STALE" : "FEED LIVE";
    $("last-update").textContent = "SYNCED " + new Date().toLocaleTimeString("en-CA", { hour12: false }) +
      (data.fetched_at ? " · SOURCE " + new Date(data.fetched_at).toLocaleTimeString("en-CA", { hour12: false }) : "");
  } catch (err) {
    $("link-chip").className = "chip chip-down";
    $("link-label").textContent = "FEED DOWN";
  }
}
refresh();
setInterval(refresh, 300000);
