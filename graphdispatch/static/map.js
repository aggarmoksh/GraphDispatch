// Map layer: stations, hospitals, hazards, incident pin, routes. maplibregl is a global (vendored UMD build).
const STYLE = "https://tiles.openfreemap.org/styles/positron";
const BOUNDS = [[-121.945, 37.30], [-121.84, 37.37]];

let map, popup, meta;
const markers = { caller: null, incident: null, hazards: [] };
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
  lines.forEach((l, i) => box.appendChild(el("p", null, l)));
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
    readyResolve();
  });
  map.on("error", (e) => { console.warn("map:", e && e.error && e.error.message); });
  return map;
}

export function setMeta(m) {
  meta = m;
  const byStation = {};
  m.units.forEach((u) => (byStation[u.station_id] ||= []).push(u.unit_id));
  m.stations.forEach((s) => {
    const b = button("st", `Station ${s.station_id}`, String(s.station_id));
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      popupFor([s.lon, s.lat], [`Station ${s.station_id} (${s.agency.toUpperCase()})`, "Units (synthetic): " + (byStation[s.station_id] || []).join(", ")]);
    });
    new maplibregl.Marker({ element: b }).setLngLat([s.lon, s.lat]).addTo(map);
  });
  m.hospitals.forEach((h) => {
    const lv = Object.entries(h.levels).map(([c, l]) => `${c.replace(/_/g, " ")} level ${l}`).join(", ");
    const b = button("hosp", `${h.name}. ${h.capabilities.length} capabilities${lv ? ". " + lv : ""}`, "H");
    b.addEventListener("click", (ev) => {
      ev.stopPropagation();
      popupFor([h.lon, h.lat], [h.name, "Offers: " + h.capabilities.map((c) => c.replace(/_/g, " ")).join(", "),
        lv ? "Designations: " + lv : "No trauma designation listed"]);
    });
    new maplibregl.Marker({ element: b }).setLngLat([h.lon, h.lat]).addTo(map);
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

export const setCaller = (lat, lon) => placeMarker("caller", "caller", "Caller location", lat, lon);
export const setIncident = (lat, lon, label) => placeMarker("incident", "pin", label || "Incident", lat, lon);

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

export async function drawRoutes(routes) {
  await ready;
  for (const kind of ["unit", "hospital"]) {
    const features = (routes || []).filter((r) => r.kind === kind && r.coords.length > 1).map((r) => ({
      type: "Feature", properties: { leg: r.leg }, geometry: { type: "LineString", coordinates: r.coords } }));
    map.getSource("route-" + kind).setData({ type: "FeatureCollection", features });
  }
}

export function fitTo(points) {
  const pts = points.filter(Boolean);
  if (!pts.length) return;
  const b = new maplibregl.LngLatBounds();
  pts.forEach((p) => b.extend(p));
  map.fitBounds(b, { padding: { top: 50, bottom: 60, left: 50, right: 50 }, maxZoom: 14, duration: 0 });
}
