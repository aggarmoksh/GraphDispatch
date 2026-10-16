// Map layer: stations, hospitals, hazards, incident pin, routes. maplibregl is a global (vendored UMD build).
import { capLabel, shortName } from "/panel.js";

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const BOUNDS = [[-121.945, 37.30], [-121.84, 37.37]];

let map, popup;
const markers = { caller: null, incident: null, hazards: [] };
const stationEls = new Map();   // station_id -> { marker, el }
const hospitalEls = new Map();  // osm_id -> { marker, el, label }
let readyResolve;
export const ready = new Promise((r) => { readyResolve = r; });

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function popupFor(lngLat, lines) {
  if (popup) popup.remove();
  const box = el("div");
  lines.forEach((l) => box.appendChild(el("p", null, l)));
  popup = new maplibregl.Popup({ offset: 14, maxWidth: "260px" }).setLngLat(lngLat).setDOMContent(box).addTo(map);
}

function button(cls, label, text) {
  const b = el("button", "mk " + cls, text || "");
  b.type = "button";
  b.setAttribute("aria-label", label);
  b.title = label;
  return b;
}

export function initMap(onClick) {
  map = new maplibregl.Map({
    container: "map", style: STYLE, bounds: BOUNDS, fitBoundsOptions: { padding: 20 },
    attributionControl: false, dragRotate: false, pitchWithRotate: false,
  });
  window.__gdMap = map; // read by the visual check
  map.touchZoomRotate.disableRotation();
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.addControl(new maplibregl.AttributionControl({ compact: false,
    customAttribution: "&copy; OpenStreetMap contributors | OpenFreeMap" }), "bottom-right");
  map.on("click", (e) => onClick(e.lngLat.lat, e.lngLat.lng));
  map.on("load", () => {
    for (const [id, color] of [["unit", "#C8102E"], ["hospital", "#1F5FBF"]]) {
      map.addSource("route-" + id, { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "route-casing-" + id, type: "line", source: "route-" + id,
        layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#FFFFFF", "line-width": 7 } });
      map.addLayer({ id: "route-line-" + id, type: "line", source: "route-" + id,
        layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": color, "line-width": 4 } });
    }
    map.addSource("closures", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "closure-casing", type: "line", source: "closures", layout: { "line-cap": "butt" }, paint: { "line-color": "#FFFFFF", "line-width": 9 } });
    map.addLayer({ id: "closure-line", type: "line", source: "closures", layout: { "line-cap": "butt" },
      paint: { "line-color": "#1D2733", "line-width": 5, "line-dasharray": [1.2, 1.2] } });
    readyResolve();
  });
  map.on("error", (e) => { console.warn("map:", e && e.error && e.error.message); });
  return map;
}

export function setMeta(m) {
  const byStation = {};
  m.units.forEach((u) => (byStation[u.station_id] ||= []).push(u.unit_id));
  m.stations.forEach((s) => {
    const b = button("st", `Station ${s.station_id}`, String(s.station_id));
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      popupFor([s.lon, s.lat], [`Station ${s.station_id} (${s.agency.toUpperCase()})`, "Units (synthetic): " + (byStation[s.station_id] || []).join(", ")]);
    });
    const marker = new maplibregl.Marker({ element: b }).setLngLat([s.lon, s.lat]).addTo(map);
    stationEls.set(s.station_id, { marker, el: b, lat: s.lat, lon: s.lon });
  });
  m.hospitals.forEach((h) => {
    const caps = h.capabilities.map(capLabel);
    const lv = Object.entries(h.levels).map(([c, l]) => `${capLabel(c)}, level ${l}`).join("; ");
    const b = button("hosp", `${h.name}. Offers: ${caps.join(", ")}${lv ? ". Designations: " + lv : ""}`, "H");
    const label = el("span", "mklabel");
    label.hidden = true;
    b.appendChild(label);
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      popupFor([h.lon, h.lat], [h.name, "Offers: " + caps.join(", "), lv ? "Designations: " + lv : "No trauma designation listed"]);
    });
    const marker = new maplibregl.Marker({ element: b }).setLngLat([h.lon, h.lat]).addTo(map);
    hospitalEls.set(h.osm_id, { marker, el: b, label, lat: h.lat, lon: h.lon, name: h.name });
  });
}

export const stationPoint = (id) => { const s = stationEls.get(id); return s ? [s.lon, s.lat] : null; };
export const hospitalPoint = (id) => { const h = hospitalEls.get(id); return h ? [h.lon, h.lat] : null; };

/** Mark the stations used by the shown decision. */
export function markStations(usedIds) {
  stationEls.forEach((s, id) => s.el.classList.toggle("used", usedIds.includes(id)));
}

/** Chosen hospital gets a filled marker; the nearest skipped hospital a grey ring and a short label. */
export function markHospitals(chosenId, skipped) {
  hospitalEls.forEach((h, id) => {
    h.el.classList.toggle("chosen", id === chosenId);
    h.el.classList.toggle("skipped", !!skipped && id === skipped.osm_id);
    h.label.hidden = !(skipped && id === skipped.osm_id);
    h.label.textContent = skipped && id === skipped.osm_id ? skipped.text : "";
    h.label.classList.remove("left");
  });
}

/** Put a hospital label on the side that stays inside the map (call after the view has moved). */
export function placeLabels() {
  const w = map.getContainer().clientWidth;
  hospitalEls.forEach((h) => {
    if (h.label.hidden) return;
    const x = map.project([h.lon, h.lat]).x;
    h.label.classList.toggle("left", x + 30 + h.label.offsetWidth > w - 8);
  });
}

function placeMarker(slot, cls, label, lat, lon) {
  if (markers[slot]) markers[slot].remove();
  markers[slot] = null;
  if (lat == null) return;
  const d = el("div", "mk " + cls);
  d.setAttribute("role", "img");
  d.setAttribute("aria-label", label);
  markers[slot] = new maplibregl.Marker({ element: d }).setLngLat([lon, lat]).addTo(map);
}

// One location marker at a time: the caller pin before a decision, the incident ring while a decision is shown.
export function setCaller(lat, lon) {
  if (lat != null) placeMarker("incident", "pin", "", null, null);
  placeMarker("caller", "caller", "Caller location", lat, lon);
}
export function setIncident(lat, lon, label) {
  if (lat != null) placeMarker("caller", "caller", "", null, null);
  placeMarker("incident", "pin", label || "Incident", lat, lon);
}

export function setHazards(list) {
  markers.hazards.forEach((m) => m.remove());
  markers.hazards = list.map((h) => {
    const b = button("haz", `Hazard: ${h.kind.replace(/_/g, " ")} at ${h.address}`);
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      popupFor([h.lon, h.lat], [`${h.kind.replace(/_/g, " ")} at ${h.address}`, h.note, h.crew_note ? "Crew note: " + h.crew_note : ""].filter(Boolean));
    });
    return new maplibregl.Marker({ element: b, offset: [20, -20] }).setLngLat([h.lon, h.lat]).addTo(map);  // beside the pin, not under it
  });
}

/** Closed road segments: dashed dark lines with a small "closed" label at the middle. */
const closedLabels = [];
export async function setClosures(list) {
  await ready;
  map.getSource("closures").setData({ type: "FeatureCollection", features: list.map((c) => ({
    type: "Feature", properties: { id: c.closure_id }, geometry: { type: "LineString", coordinates: c.geometry } })) });
  closedLabels.splice(0).forEach((m) => m.remove());
  list.forEach((c) => {
    const [a, b] = c.geometry;
    const d = el("div", "mk closedlabel", "closed");
    d.setAttribute("role", "img");
    d.setAttribute("aria-label", `Closed road: ${c.name || "unnamed road"}`);
    closedLabels.push(new maplibregl.Marker({ element: d, offset: [0, -14] }).setLngLat([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]).addTo(map));
  });
}

export const setClosing = (on) => map.getContainer().classList.toggle("map-closing", on);

export async function drawRoutes(routes) {
  await ready;
  for (const kind of ["unit", "hospital"]) {
    const features = (routes || []).filter((r) => r.kind === kind && r.coords.length > 1).map((r) => ({
      type: "Feature", properties: { leg: r.leg }, geometry: { type: "LineString", coordinates: r.coords } }));
    map.getSource("route-" + kind).setData({ type: "FeatureCollection", features });
  }
}

/** Fit the view to the decision with padding that keeps everything clear of the legend and map controls. */
export function fitTo(points) {
  const pts = points.filter(Boolean);
  if (!pts.length) return;
  const mobile = window.matchMedia("(max-width: 759px)").matches;
  const padding = mobile ? { top: 56, left: 64, right: 56, bottom: 48 } : { top: 56, left: 210, right: 72, bottom: 52 };
  const b = new maplibregl.LngLatBounds();
  pts.forEach((p) => b.extend(p));
  map.resize();
  map.fitBounds(b, { padding, maxZoom: 15, duration: 0 });
  window.__gdLastFit = pts;
  placeLabels();
}
