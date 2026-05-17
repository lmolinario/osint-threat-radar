import L from "leaflet";
import "leaflet/dist/leaflet.css";

const API_BASE = "https://osint-threat-radar.onrender.com";

function api(path) {
  return `${API_BASE}${path}`;
}

const statusEl = document.getElementById("status");
const eventsEl = document.getElementById("events");
const qEl = document.getElementById("q");
const typeEl = document.getElementById("type");
const sourceEl = document.getElementById("source");
const refreshBtn = document.getElementById("refresh");
const clearMapsBtn = document.getElementById("clearMapsBtn");
const activeMapsList = document.getElementById("activeMapsList");
const aircraftToggle = document.getElementById("aircraftToggle");
const shipsToggle = document.getElementById("shipsToggle");
const milToggle = document.getElementById("milToggle");
const earthIntelBtn = document.getElementById("earthIntelBtn");
const quickSpaceBtn = document.getElementById("quickSpaceBtn");
const quickMobilityBtn = document.getElementById("quickMobilityBtn");

const map = L.map("map", {
  zoomControl: false,
}).setView([41.9, 12.5], 5);

L.control.zoom({ position: "topright" }).addTo(map);

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
}).addTo(map);

const markersLayer = L.layerGroup().addTo(map);
const aircraftLayer = L.layerGroup().addTo(map);
const shipsLayer = L.layerGroup().addTo(map);
let aircraftTimer = null;
let shipsTimer = null;
let didAutoFitEvents = false;

function setStatus(msg) {
  statusEl.textContent = msg;
}

function esc(s) {
  return (s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

function setEventFilters(source = "", type = "", q = "") {
  sourceEl.value = source;
  typeEl.value = type;
  qEl.value = q;
  didAutoFitEvents = false;
}

function buildQuery() {
  const params = new URLSearchParams();
  const q = qEl.value.trim();
  const type = typeEl.value.trim();
  const source = sourceEl.value.trim();

  if (q) params.set("q", q);
  if (type) params.set("type", type);
  if (source) params.set("source", source);
  params.set("limit", "200");
  return params.toString();
}

function eventClass(type) {
  if (["earthquake", "disaster", "flood", "wildfire", "cyclone", "volcano", "drought", "severe_weather"].includes(type)) {
    return "ev-earth";
  }
  if (type === "military_event") return "ev-mil";
  return "ev-news";
}

function eventIcon(type, severity = 20) {
  const glyphByType = {
    earthquake: "●",
    flood: "≈",
    wildfire: "▲",
    cyclone: "◎",
    volcano: "◆",
    drought: "□",
    severe_weather: "✦",
    disaster: "■",
    military_event: "⚑",
    news: "•",
  };

  const size = severity >= 75 ? 20 : severity >= 55 ? 17 : 14;
  const glyph = glyphByType[type] || "•";
  const cls = eventClass(type);

  return L.divIcon({
    className: "event-icon",
    html: `<div class="${cls}" style="font-size:${size}px; line-height:${size}px;">${glyph}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function activeMaps() {
  const active = [];
  if (aircraftToggle?.checked) active.push({ id: "aircraft", name: "Aerei live OpenSky", icon: "✈" });
  if (shipsToggle?.checked) active.push({ id: "ships", name: "Navi AIS demo/provider", icon: "▲" });
  if (satellitesToggle?.checked) active.push({ id: "satellites", name: `Satelliti ${satGroupEl?.value || "stations"}`, icon: "◆" });
  if (milToggle?.checked || sourceEl?.value === "military_osint") active.push({ id: "military", name: "Eventi militari OSINT", icon: "⚑" });
  if (sourceEl?.value === "usgs" || sourceEl?.value === "gdacs" || ["earthquake", "disaster", "flood", "wildfire", "cyclone", "volcano", "drought", "severe_weather"].includes(typeEl?.value)) {
    active.push({ id: "earth", name: "Earth Intelligence", icon: "●" });
  }
  if (!sourceEl?.value && !typeEl?.value && !qEl?.value) active.push({ id: "events", name: "All events stream", icon: "•" });
  return active;
}

function renderActiveMaps() {
  if (!activeMapsList) return;
  const active = activeMaps();

  if (active.length === 0) {
    activeMapsList.innerHTML = `<div class="active-empty">No active maps selected.</div>`;
    return;
  }

  activeMapsList.innerHTML = active.map((item) => `
    <div class="active-map-row" data-layer="${esc(item.id)}">
      <div class="active-icon">${esc(item.icon)}</div>
      <div class="active-name">${esc(item.name)}</div>
      <button class="active-remove" data-remove-layer="${esc(item.id)}">×</button>
    </div>
  `).join("");

  activeMapsList.querySelectorAll("[data-remove-layer]").forEach((btn) => {
    btn.addEventListener("click", async () => removeActiveLayer(btn.dataset.removeLayer));
  });
}

async function removeActiveLayer(layerId) {
  if (layerId === "aircraft") {
    aircraftToggle.checked = false;
    if (aircraftTimer) clearInterval(aircraftTimer);
    aircraftTimer = null;
    aircraftLayer.clearLayers();
  }
  if (layerId === "ships") {
    shipsToggle.checked = false;
    if (shipsTimer) clearInterval(shipsTimer);
    shipsTimer = null;
    shipsLayer.clearLayers();
  }
  if (layerId === "satellites") {
    satellitesToggle.checked = false;
    stopSatellites();
  }
  if (layerId === "military") {
    milToggle.checked = false;
    if (sourceEl.value === "military_osint") setEventFilters("", "", "");
    await loadEvents();
  }
  if (layerId === "earth") {
    if (sourceEl.value === "usgs" || sourceEl.value === "gdacs") sourceEl.value = "";
    if (["earthquake", "disaster", "flood", "wildfire", "cyclone", "volcano", "drought", "severe_weather"].includes(typeEl.value)) typeEl.value = "";
    await loadEvents();
  }
  if (layerId === "events") {
    markersLayer.clearLayers();
    eventsEl.innerHTML = "";
    setStatus("Event stream cleared.");
  }
  renderActiveMaps();
}

async function clearAllMaps() {
  aircraftToggle.checked = false;
  shipsToggle.checked = false;
  satellitesToggle.checked = false;
  milToggle.checked = false;

  if (aircraftTimer) clearInterval(aircraftTimer);
  if (shipsTimer) clearInterval(shipsTimer);
  if (satellitesTimer) clearInterval(satellitesTimer);
  aircraftTimer = null;
  shipsTimer = null;
  satellitesTimer = null;

  aircraftLayer.clearLayers();
  shipsLayer.clearLayers();
  satellitesLayer.clearLayers();
  markersLayer.clearLayers();
  eventsEl.innerHTML = "";
  setEventFilters("", "", "");
  setStatus("All maps cleared.");
  renderActiveMaps();
}

async function loadAircraft() {
  aircraftLayer.clearLayers();

  const b = map.getBounds();
  const lamin = b.getSouth();
  const lamax = b.getNorth();
  const lomin = b.getWest();
  const lomax = b.getEast();

  const url = api(`/aircraft?lamin=${lamin}&lamax=${lamax}&lomin=${lomin}&lomax=${lomax}`);
  const res = await fetch(url);
  if (!res.ok) return;

  const data = await res.json();
  const features = data.features || [];

  for (const f of features) {
    if (!f.geometry || f.geometry.type !== "Point") continue;

    const [lon, lat] = f.geometry.coordinates;
    const p = f.properties || {};

    const callsign = (p.callsign || "").trim() || f.id;
    const alt = p.geo_altitude != null ? Math.round(p.geo_altitude) : "n/a";
    const spd = p.velocity != null ? Math.round(p.velocity) : "n/a";
    const trk = p.track != null ? Number(p.track) : 0;

    const icon = L.divIcon({
      className: "aircraft-icon",
      html: `<div style="transform: rotate(${trk}deg); transform-origin: center; font-size: 18px; line-height: 18px;">✈</div>`,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });

    const m = L.marker([lat, lon], { icon });
    m.bindPopup(
      `<b>${esc(callsign)}</b><br/>Alt: ${alt} m<br/>Vel: ${spd} m/s<br/>Track: ${Math.round(trk)}°<br/>${esc(p.country || "")}`
    );
    m.addTo(aircraftLayer);
  }

  setStatus(`Aerei: ${features.length}${data.stale ? " / stale" : ""}`);
  renderActiveMaps();
}

async function loadShips() {
  shipsLayer.clearLayers();

  const b = map.getBounds();
  const lamin = b.getSouth();
  const lamax = b.getNorth();
  const lomin = b.getWest();
  const lomax = b.getEast();

  const url = api(`/ships?demo=true&lamin=${lamin}&lamax=${lamax}&lomin=${lomin}&lomax=${lomax}`);
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) return;

  const data = await res.json();
  const features = data.features || [];

  for (const f of features) {
    if (!f.geometry || f.geometry.type !== "Point") continue;

    const [lon, lat] = f.geometry.coordinates;
    const p = f.properties || {};
    const course = p.course_deg != null ? Number(p.course_deg) : 0;
    const name = p.name || f.id;

    const icon = L.divIcon({
      className: "ship-icon",
      html: `<div style="transform: rotate(${course}deg); transform-origin: center; font-size: 18px; line-height: 18px;">▲</div>`,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });

    const m = L.marker([lat, lon], { icon });
    m.bindPopup(
      `<b>${esc(name)}</b><br/>Type: ${esc(p.ship_type || "n/a")}<br/>MMSI: ${esc(p.mmsi || "n/a")}<br/>Speed: ${esc(String(p.speed_kn ?? "n/a"))} kn<br/>Course: ${Math.round(course)}°<br/>Destination: ${esc(p.destination || "n/a")}<br/><small>${esc(p.source || "")}</small>`
    );
    m.addTo(shipsLayer);
  }

  setStatus(`Navi: ${features.length}${data.demo ? " / demo" : ""}`);
  renderActiveMaps();
}

async function loadEvents() {
  setStatus("Caricamento eventi...");
  markersLayer.clearLayers();
  eventsEl.innerHTML = "";

  const qs = buildQuery();
  const url = api(`/events${qs ? `?${qs}` : ""}`);
  const res = await fetch(url);

  if (!res.ok) {
    setStatus(`Errore HTTP ${res.status}`);
    return;
  }

  const data = await res.json();
  const features = data.features || [];
  setStatus(`Eventi: ${features.length}`);

  const bounds = [];

  for (const f of features) {
    const p = f.properties || {};
    const title = p.title || "(no title)";
    const ts = p.ts || "";
    const url = p.url || "";
    const summary = p.summary || "";
    const severity = Number(p.severity || 20);

    const div = document.createElement("div");
    div.className = "event";
    if (p.type === "military_event") div.style.borderLeftColor = "rgba(249,115,22,.9)";
    if (["earthquake", "disaster", "flood", "wildfire", "cyclone", "volcano", "drought", "severe_weather"].includes(p.type)) {
      div.style.borderLeftColor = "rgba(34,197,94,.9)";
    }
    div.innerHTML = `
      <h4>${esc(title)}</h4>
      <small>${esc(p.source)} • ${esc(p.type)} • severity ${severity} • ${esc(ts)}</small>
      ${summary ? `<div class="summary">${esc(summary).slice(0, 260)}</div>` : ""}
      ${url ? `<div style="margin-top:6px;"><a href="${esc(url)}" target="_blank" rel="noreferrer">Apri fonte</a></div>` : ""}
    `;
    eventsEl.appendChild(div);

    if (f.geometry && f.geometry.type === "Point") {
      const [lon, lat] = f.geometry.coordinates;
      const m = L.marker([lat, lon], { icon: eventIcon(p.type, severity) }).addTo(markersLayer);
      m.bindPopup(
        `<b>${esc(title)}</b><br/><small>${esc(p.source)} • ${esc(p.type)} • severity ${severity}</small><br/><small>${esc(ts)}</small>`
      );
      bounds.push([lat, lon]);
    }
  }

  if (!didAutoFitEvents && bounds.length > 0) {
    didAutoFitEvents = true;
    map.fitBounds(bounds, { padding: [30, 30] });
  }
  renderActiveMaps();
}

async function showEarthIntel() {
  setStatus("Aggiornamento Earth Intelligence...");

  try {
    await fetch(api("/refresh/earth-intel"), { method: "POST", cache: "no-store" });
  } catch (e) {
    console.warn("Earth intel manual refresh failed, showing cached events", e);
  }

  setEventFilters("", "", "");
  await loadEvents();
}

async function showMilitaryEvents() {
  setStatus("Aggiornamento eventi militari OSINT...");

  try {
    await fetch(api("/refresh/military-events"), { method: "POST", cache: "no-store" });
  } catch (e) {
    console.warn("Military OSINT manual refresh failed, showing cached events", e);
  }

  setEventFilters("military_osint", "", "");
  await loadEvents();
}

const satellitesToggle = document.getElementById("satellitesToggle");
const satellitesLayer = L.layerGroup().addTo(map);
let satellitesTimer = null;
const satGroupEl = document.getElementById("satGroup");

satGroupEl?.addEventListener("change", () => {
  if (satellitesToggle?.checked) refreshSatellites();
  renderActiveMaps();
});

function clearSatellites() {
  satellitesLayer.clearLayers();
}

function addSatelliteMarker(s) {
  const icon = L.divIcon({
    className: "sat-icon",
    html: `<div style="font-size: 18px; line-height: 18px;">◆</div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });

  const m = L.marker([s.lat, s.lon], { icon }).bindPopup(
    `<b>${esc(s.name)}</b><br/>
    NORAD: ${esc(String(s.norad_id ?? ""))}<br/>
    Lat: ${s.lat.toFixed(3)}<br/>
    Lon: ${s.lon.toFixed(3)}<br/>
    Alt: ${Number(s.alt_km).toFixed(1)} km<br/>
    Vel: ${Number(s.speed_kms).toFixed(2)} km/s<br/>
    <small>${esc(s.source_format || "")}</small>`
  );

  m.addTo(satellitesLayer);
}

async function refreshSatellites() {
  try {
    satellitesLayer.clearLayers();

    const group = satGroupEl?.value || "stations";
    const b = map.getBounds();
    const lamin = b.getSouth();
    const lamax = b.getNorth();
    const lomin = b.getWest();
    const lomax = b.getEast();

    const url = api(`/satellites?group=${encodeURIComponent(group)}&limit=1000&lamin=${lamin}&lamax=${lamax}&lomin=${lomin}&lomax=${lomax}`);
    const r = await fetch(url, { cache: "no-store" });

    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();

    for (const s of data.items || []) addSatelliteMarker(s);

    setStatus(`Satelliti ${group}: ${data.count}${data.truncated ? " / truncated" : ""}`);
  } catch (e) {
    console.error(e);
    setStatus(`Satelliti: errore (${e.message})`);
  }
  renderActiveMaps();
}

function startSatellites(intervalMs = 30000) {
  stopSatellites();
  refreshSatellites();
  satellitesTimer = setInterval(refreshSatellites, intervalMs);
}

function stopSatellites() {
  if (satellitesTimer) {
    clearInterval(satellitesTimer);
    satellitesTimer = null;
  }
  clearSatellites();
  renderActiveMaps();
}

satellitesToggle?.addEventListener("change", (e) => {
  if (e.target.checked) startSatellites(30000);
  else stopSatellites();
  renderActiveMaps();
});

shipsToggle?.addEventListener("change", async (e) => {
  if (e.target.checked) {
    await loadShips();
    shipsTimer = setInterval(loadShips, 30000);
  } else {
    if (shipsTimer) clearInterval(shipsTimer);
    shipsTimer = null;
    shipsLayer.clearLayers();
  }
  renderActiveMaps();
});

milToggle?.addEventListener("change", async (e) => {
  if (e.target.checked) {
    await showMilitaryEvents();
  } else if (sourceEl.value === "military_osint") {
    setEventFilters("", "", "");
    await loadEvents();
  }
  renderActiveMaps();
});

refreshBtn.addEventListener("click", loadEvents);
clearMapsBtn?.addEventListener("click", clearAllMaps);
earthIntelBtn?.addEventListener("click", showEarthIntel);
[qEl, typeEl, sourceEl].forEach((el) => el.addEventListener("change", async () => {
  await loadEvents();
  renderActiveMaps();
}));

document.querySelectorAll(".quick-filter").forEach((btn) => {
  btn.addEventListener("click", async () => {
    setEventFilters(btn.dataset.source || "", btn.dataset.type || "", "");
    await loadEvents();
    renderActiveMaps();
  });
});

quickSpaceBtn?.addEventListener("click", async () => {
  satellitesToggle.checked = true;
  satGroupEl.value = satGroupEl.value || "stations";
  startSatellites(30000);
  renderActiveMaps();
});

quickMobilityBtn?.addEventListener("click", async () => {
  aircraftToggle.checked = true;
  shipsToggle.checked = true;
  await loadAircraft();
  await loadShips();
  if (!aircraftTimer) aircraftTimer = setInterval(loadAircraft, 10000);
  if (!shipsTimer) shipsTimer = setInterval(loadShips, 30000);
  renderActiveMaps();
});

aircraftToggle.addEventListener("change", async () => {
  if (aircraftToggle.checked) {
    await loadAircraft();
    aircraftTimer = setInterval(loadAircraft, 10000);
  } else {
    if (aircraftTimer) clearInterval(aircraftTimer);
    aircraftTimer = null;
    aircraftLayer.clearLayers();
  }
  renderActiveMaps();
});

map.on("moveend", () => {
  if (aircraftToggle.checked) loadAircraft();
  if (shipsToggle?.checked) loadShips();
  if (satellitesToggle?.checked) refreshSatellites();
});

loadEvents();
renderActiveMaps();
setInterval(loadEvents, 60_000);
