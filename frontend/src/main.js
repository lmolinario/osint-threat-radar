import L from "leaflet";
import "leaflet/dist/leaflet.css";

const statusEl = document.getElementById("status");
const eventsEl = document.getElementById("events");
const qEl = document.getElementById("q");
const typeEl = document.getElementById("type");
const sourceEl = document.getElementById("source");
const refreshBtn = document.getElementById("refresh");
const aircraftToggle = document.getElementById("aircraftToggle");

const map = L.map("map").setView([41.9, 12.5], 5);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const markersLayer = L.layerGroup().addTo(map);
const aircraftLayer = L.layerGroup().addTo(map);
let aircraftTimer = null;
let didAutoFitEvents = false;

function setStatus(msg) {
  statusEl.textContent = msg;
}

function esc(s) {
  return (s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
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


async function loadAircraft() {
  aircraftLayer.clearLayers();

  const b = map.getBounds();
  const lamin = b.getSouth();
  const lamax = b.getNorth();
  const lomin = b.getWest();
  const lomax = b.getEast();

  const url = `/api/aircraft?lamin=${lamin}&lamax=${lamax}&lomin=${lomin}&lomax=${lomax}`;

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
        html: `<div style="
          transform: rotate(${trk}deg);
          transform-origin: center;
          font-size: 16px;
          line-height: 16px;
          ">✈</div>`,
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });

      const m = L.marker([lat, lon], { icon });
      m.bindPopup(
        `<b>${callsign}</b><br/>Alt: ${alt} m<br/>Vel: ${spd} m/s<br/>Track: ${Math.round(trk)}°<br/>${p.country || ""}`
      );
      m.addTo(aircraftLayer);
    }
}



async function loadEvents() {
  setStatus("Caricamento...");
  markersLayer.clearLayers();
  eventsEl.innerHTML = "";

  const qs = buildQuery();
  const url = `/api/events${qs ? `?${qs}` : ""}`;

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

    // Sidebar card
    const div = document.createElement("div");
    div.className = "event";
    div.innerHTML = `
      <h4>${esc(title)}</h4>
      <small>${esc(p.source)} • ${esc(p.type)} • ${esc(ts)}</small>
      ${url ? `<div style="margin-top:6px;"><a href="${esc(url)}" target="_blank" rel="noreferrer">Apri fonte</a></div>` : ""}
    `;
    eventsEl.appendChild(div);

    // Map marker (solo se c'è geometry)
    if (f.geometry && f.geometry.type === "Point") {
      const [lon, lat] = f.geometry.coordinates;
      const m = L.marker([lat, lon]).addTo(markersLayer);
      m.bindPopup(`<b>${esc(title)}</b><br/><small>${esc(ts)}</small>`);
      bounds.push([lat, lon]);
    }
  }

    if (!didAutoFitEvents && bounds.length > 0) {
      didAutoFitEvents = true;
      map.fitBounds(bounds, { padding: [30, 30] });
    }
}

const satellitesToggle = document.getElementById("satellitesToggle");
const satellitesLayer = L.layerGroup().addTo(map);
let satellitesTimer = null;
const satGroupEl = document.getElementById("satGroup");

satGroupEl?.addEventListener("change", () => {
  if (satellitesToggle?.checked) refreshSatellites();
});

function clearSatellites() {
  satellitesLayer.clearLayers();
}

function addSatelliteMarker(s) {
  const m = L.circleMarker([s.lat, s.lon], {
    radius: 5,
    weight: 1,
    fillOpacity: 0.7,
  }).bindPopup(
    `<b>${esc(s.name)}</b><br/>
    NORAD: ${esc(String(s.norad_id ?? ""))}<br/>
    Lat: ${s.lat.toFixed(3)}<br/>
    Lon: ${s.lon.toFixed(3)}<br/>
    Alt: ${Number(s.alt_km).toFixed(1)} km<br/>
    Vel: ${Number(s.speed_kms).toFixed(2)} km/s`
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

    const url = `/api/satellites?group=${encodeURIComponent(group)}&lamin=${lamin}&lamax=${lamax}&lomin=${lomin}&lomax=${lomax}`;

    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();

    for (const s of data.items || []) addSatelliteMarker(s);

    setStatus(`Satelliti (viewport): ${data.count}`);
  } catch (e) {
    console.error(e);
    setStatus(`Satelliti: errore (${e.message})`);
  }
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
}

satellitesToggle?.addEventListener("change", (e) => {
  if (e.target.checked) startSatellites(30000);
  else stopSatellites();
});


refreshBtn.addEventListener("click", loadEvents);
[qEl, typeEl, sourceEl].forEach((el) => el.addEventListener("change", loadEvents));

aircraftToggle.addEventListener("change", async () => {

  if (aircraftToggle.checked) {

    await loadAircraft();

    aircraftTimer = setInterval(loadAircraft, 10000);

  } else {

    if (aircraftTimer) clearInterval(aircraftTimer);

    aircraftTimer = null;

    aircraftLayer.clearLayers();
  }

});

map.on("moveend", () => {
  if (aircraftToggle.checked) loadAircraft();
  if (satellitesToggle?.checked) refreshSatellites();
});


loadEvents();
setInterval(loadEvents, 60_000);