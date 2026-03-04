import L from "leaflet";
import "leaflet/dist/leaflet.css";

/* global L */
const statusEl = document.getElementById("status");
const eventsEl = document.getElementById("events");
const qEl = document.getElementById("q");
const typeEl = document.getElementById("type");
const sourceEl = document.getElementById("source");
const refreshBtn = document.getElementById("refresh");

const map = L.map("map").setView([41.9, 12.5], 5); // Italia
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const markersLayer = L.layerGroup().addTo(map);

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

  if (bounds.length > 0) {
    map.fitBounds(bounds, { padding: [30, 30] });
  }
}

refreshBtn.addEventListener("click", loadEvents);
[qEl, typeEl, sourceEl].forEach((el) => el.addEventListener("change", loadEvents));

loadEvents();
setInterval(loadEvents, 60_000);