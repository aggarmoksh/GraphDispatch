import { api } from "/api.js";
import { initMap, setMeta, setCaller, setIncident, setHazards, drawRoutes, fitTo, ready, markStations, markHospitals,
  stationPoint, hospitalPoint, setClosures, setClosing } from "/map.js";
import { renderDecision, renderWhy, setLabels, typeLabel, skipText, mmss } from "/panel.js";

const $ = (id) => document.getElementById(id);
const state = { meta: null, loc: null, preset: null, history: [], current: -1, busy: false, closeMode: false, closures: [], closureQueries: null, clockOffset: 0 };

const PRESETS = {
  stroke: { lat: 37.3300, lon: -121.9300, type: "stroke", addr: "",
    text: "My wife's face is drooping on one side and she can't lift her right arm, it started ten minutes ago" },
  burn: { lat: 37.3600, lon: -121.8550, type: "burn", addr: "",
    text: "A pot of oil caught fire, I put it out but my son's arm is badly burned and blistering" },
  oxygen: { lat: 37.3360, lon: -121.8900, type: "structure_fire", addr: "200 Demo Street",
    text: "Smoke coming out of the garage at 200 Demo Street, my neighbor uses home oxygen, please hurry",
    text2: "My neighbor at 200 Demo St just collapsed and isn't breathing" },
  closure: { lat: 37.3300, lon: -121.9300, type: "stroke", addr: "",
    text: "My wife's face is drooping on one side and she can't lift her right arm, it started ten minutes ago" },
};

function setStatus(msg, kind = "") {
  const s = $("status");
  s.textContent = msg;
  s.className = "status" + (kind ? " " + kind : "");
}

function setBusy(b) {
  state.busy = b;
  $("take").disabled = b;
  document.querySelectorAll(".preset").forEach((x) => (x.disabled = b));
}

function setLoc(lat, lon) {
  state.loc = { lat, lon };
  setCaller(lat, lon);          // also removes the previous incident ring: never two location markers
  drawRoutes([]);
  markStations([]);
  markHospitals(null, null);
  const p = $("loc");
  p.replaceChildren(document.createTextNode("Caller location: "));
  const m = document.createElement("span");
  m.className = "mono";
  m.textContent = `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
  p.appendChild(m);
}

function applyMode() {
  const g = $("graph-only").checked;
  $("ai-fields").hidden = g;
  $("graph-fields").hidden = !g;
}

function clearPreset() {
  state.preset = null;
  document.querySelectorAll(".preset").forEach((b) => b.setAttribute("aria-pressed", "false"));
}

function pickPreset(key) {
  const p = PRESETS[key];
  state.preset = key;
  document.querySelectorAll(".preset").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.preset === key)));
  setLoc(p.lat, p.lon);
  $("text").value = p.text;
  $("itype").value = p.type;
  $("addr").value = p.addr;
  fitTo([[p.lon, p.lat]]);
  setStatus(key === "oxygen"
    ? "This preset makes two calls at the same address. Press Take call to run both."
    : key === "closure"
      ? "This preset closes two synthetic roads on the stroke route, then takes the call. Press Take call."
      : "Preset loaded. Press Take call.");
}

// ---------------------------------------------------------------- decisions
const ctx = {
  onWhy(name, btn) {
    const cur = state.history[state.current];
    if (!cur) return;
    document.querySelectorAll(".qline").forEach((b) => b.removeAttribute("aria-current"));
    btn.setAttribute("aria-current", "true");
    openDrawer(true);
    let payload = cur.payload;
    if ((name === "close_road" || name === "reopen_road") && state.closureQueries) {
      // closing happens in its own request: show the real recorded run if there is one, else the query text
      const ran = (state.lastCloseQueries || []).filter((q) => q.name === name);
      payload = { queries: ran.length ? ran : [{ name, cypher: state.closureQueries[name], ms: 0, params: {} }] };
    }
    renderWhy($("why-body"), payload, name);
    $("why-hint").textContent = `Showing the query behind: ${btn.textContent.slice(0, 80)}`;
  },
  async onDispatch(p) {
    await guarded(async () => {
      setStatus("Dispatching…");
      const r = await api(`/api/dispatch/${p.decision_id}`, { method: "POST" });
      const cur = state.history[state.current];
      cur.payload = { ...cur.payload, incident: r.incident, queries: cur.payload.queries.concat(r.queries) };
      show(cur.payload);
      setStatus(`Dispatched. ${p.units.map((u) => u.unit_id).join(", ")} are now assigned (synthetic).`, "ok");
    });
  },
  async onClear(p) {
    await guarded(async () => {
      setStatus("Clearing…");
      const r = await api(`/api/clear/${p.incident.incident_id}`, { method: "POST" });
      const cur = state.history[state.current];
      cur.payload = { ...cur.payload, incident: { ...cur.payload.incident, status: "cleared" }, queries: cur.payload.queries.concat(r.queries) };
      show(cur.payload);
      await drawRoutes([]);
      setStatus(`Incident cleared. ${r.units_released} unit${r.units_released === 1 ? "" : "s"} available again.`, "ok");
    });
  },
};

function openDrawer(open) {
  $("why").dataset.open = String(open);
  $("why-body").hidden = !open;
  const t = $("why-toggle");
  t.setAttribute("aria-expanded", String(open));
  t.textContent = open ? "Hide" : "Show";
}

async function refreshHazards() {
  try {
    const r = await api("/api/incidents");
    setHazards(r.hazards);
  } catch { /* hazards are decoration; the decision already rendered */ }
}

function show(payload) {
  renderDecision($("decision"), payload, ctx);
  const inc = payload.incident;
  setIncident(inc.lat, inc.lon, `Incident at ${inc.address}`);
}

/** Mark hospitals and stations for this decision and fit the map to everything it uses. */
function followOnMap(payload) {
  const stations = [...new Set(payload.units.map((u) => u.station_id))];
  const chosen = payload.destination ? payload.destination.osm_id : null;
  const sk = payload.skipped[0];
  const skipped = sk ? { osm_id: sk.osm_id, text: (/\(nearest\)/.test(sk.reason) ? "Nearest, skipped: " : "Skipped: ") + skipText(sk.reason).replace(/ \(nearest\)$/, "") } : null;
  markStations(stations);
  markHospitals(chosen, skipped);
  const pts = [[payload.incident.lon, payload.incident.lat], ...stations.map(stationPoint),
    chosen != null ? hospitalPoint(chosen) : null, sk ? hospitalPoint(sk.osm_id) : null,
    ...payload.routes.flatMap((r) => r.coords)];
  (payload.rerouted || []).forEach((x) => {
    const c = state.closures.find((k) => k.closure_id === x.closure_id);
    if (c) pts.push(...c.geometry);
  });
  fitTo(pts);
}

async function present(payload, label) {
  state.history.push({ label, payload });
  state.current = state.history.length - 1;
  renderHistory();
  show(payload);
  await drawRoutes(inc_routes(payload));
  followOnMap(payload);
  await refreshHazards();
  $("panel").focus({ preventScroll: true });
  if (window.matchMedia("(min-width: 760px)").matches) $("panel").scrollIntoView({ block: "start" });
}

const inc_routes = (p) => (p.incident.status === "cleared" ? [] : p.routes);

function renderHistory() {
  const box = $("history");
  box.hidden = state.history.length < 2;
  box.replaceChildren();
  state.history.forEach((h, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = h.label;
    b.setAttribute("aria-current", String(i === state.current));
    b.addEventListener("click", async () => {
      state.current = i;
      renderHistory();
      show(h.payload);
      await drawRoutes(inc_routes(h.payload));
      followOnMap(h.payload);
    });
    box.appendChild(b);
  });
}

async function guarded(fn) {
  if (state.busy) return;
  setBusy(true);
  try {
    await fn();
  } catch (e) {
    setStatus(e.message, "error");
    if (e.status === 429) { $("graph-only").checked = true; applyMode(); }
  } finally {
    setBusy(false);
  }
}

// ---------------------------------------------------------------- road closures
function renderClosures() {
  const ul = $("clo-list");
  ul.replaceChildren();
  const now = Date.now() / 1000 + state.clockOffset;
  state.closures.forEach((c) => {
    const li = document.createElement("li");
    const t = document.createElement("span");
    t.textContent = `${c.name || "Unnamed road"}`;
    const sub = document.createElement("span");
    sub.className = "sub";
    sub.textContent = `${c.reason}; reopens by itself in ${mmss(Math.max(0, c.expires_at - now))}`;
    t.appendChild(sub);
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = "Reopen";
    b.setAttribute("aria-label", `Reopen ${c.name || "unnamed road"}`);
    b.addEventListener("click", () => guarded(async () => {
      await api(`/api/closures/${c.closure_id}`, { method: "DELETE" });
      await refreshClosures();
      setStatus("Road reopened. Decisions already taken keep what they recorded.", "ok");
    }));
    li.append(t, b);
    ul.appendChild(li);
  });
  if (!state.closures.length) {
    const li = document.createElement("li");
    li.className = "sub";
    li.textContent = "No roads are closed.";
    li.style.borderLeft = "0";
    ul.appendChild(li);
  }
}

async function refreshClosures() {
  try {
    const r = await api("/api/closures");
    state.closures = r.closures;
    state.closureQueries = r.closure_queries;
    state.clockOffset = r.now - Date.now() / 1000;
    await setClosures(r.closures);
    renderClosures();
  } catch { /* closures are an extra; the rest of the page still works */ }
}

function setCloseMode(on) {
  state.closeMode = on;
  $("close-toggle").setAttribute("aria-pressed", String(on));
  setClosing(on);
  if (on) setStatus("Click a road on the map to close it.");
}

async function closeAt(lat, lon) {
  setCloseMode(false);
  await guarded(async () => {
    const r = await api("/api/closures", { method: "POST", body: { lat, lon, reason: "Synthetic closure" } });
    state.lastCloseQueries = r.queries;
    await refreshClosures();
    setStatus(`Closed ${r.closure.name || "an unnamed road"}. Take a call to see the routes go around it.`, "ok");
  });
}

async function closeDemoRoads() {
  await refreshClosures();
  const active = new Set(state.closures.map((k) => [k.src_osm, k.dst_osm].sort().join("-")));
  for (const c of state.meta.demo_closures) {
    if (active.has([c.src_osm, c.dst_osm].sort().join("-"))) continue;          // already closed: no request, no error
    try {
      const r = await api("/api/closures", { method: "POST", body: { src_osm: c.src_osm, dst_osm: c.dst_osm, reason: c.reason } });
      state.lastCloseQueries = r.queries;
    } catch (e) {
      if (!(e.status === 409 && /already closed|no open road/i.test(e.message))) throw e;   // already closed is fine
    }
  }
  await refreshClosures();
}

async function graphCall(type, address) {
  return api("/api/recommend", { method: "POST", body: { lat: state.loc.lat, lon: state.loc.lon, incident_type: type, address } });
}

async function takeCall() {
  if (!state.loc) { setStatus("Click the map to place a caller, or pick a preset.", "error"); return; }
  const graphOnly = $("graph-only").checked;
  await guarded(async () => {
    setStatus(graphOnly ? "Walking the graph…" : "Reading the call, then walking the graph…");
    if (state.preset === "closure") {
      setStatus("Closing two synthetic roads on the stroke route…");
      await closeDemoRoads();
      setStatus(graphOnly ? "Walking the graph around the closures…" : "Reading the call, then walking the graph around the closures…");
    }
    if (state.preset === "oxygen") {
      const p = PRESETS.oxygen;
      if (graphOnly) {
        // The AI path extracts the oxygen hazard from call 1; here the operator records it first, then both calls follow.
        await api("/api/hazard", { method: "POST", body: { address: p.addr, kind: "oxygen_storage", note: "Home oxygen next door (preset)", lat: p.lat, lon: p.lon } });
        setStatus("Call 1 of 2: garage fire…");
        await present(await graphCall("structure_fire", p.addr), `Call ${state.history.length + 1}: structure fire`);
        setStatus("Call 2 of 2: collapse next door…");
        await present(await graphCall("cardiac_arrest", "200 Demo St"), `Call ${state.history.length + 1}: cardiac arrest`);
      } else {
        setStatus("Call 1 of 2: garage fire…");
        await present(await api("/api/call", { method: "POST", body: { text: p.text, lat: p.lat, lon: p.lon } }), `Call ${state.history.length + 1}: structure fire`);
        setStatus("Call 2 of 2: collapse next door…");
        await present(await api("/api/call", { method: "POST", body: { text: p.text2, lat: p.lat, lon: p.lon } }), `Call ${state.history.length + 1}: cardiac arrest`);
      }
      setStatus("Both calls done. The second call remembered the first.", "ok");
      return;
    }
    let payload;
    if (graphOnly) {
      payload = await graphCall($("itype").value, $("addr").value.trim());
    } else {
      const text = $("text").value.trim();
      if (text.length < 3) throw new Error("Type what the caller says, or switch to Graph only.");
      payload = await api("/api/call", { method: "POST", body: { text, lat: state.loc.lat, lon: state.loc.lon } });
    }
    await present(payload, `Call ${state.history.length + 1}: ${typeLabel(payload.incident.type)}`);
    setStatus(`Recommendation ready in ${payload.total_ms} ms. Nothing is dispatched until you confirm.`, "ok");
    if (state.preset === "closure") await refreshClosures();
  });
}

// ---------------------------------------------------------------- start
async function start() {
  initMap((lat, lon) => {
    if (state.busy) return;
    if (state.closeMode) { closeAt(lat, lon); return; }
    clearPreset(); setLoc(lat, lon); setStatus("");
  });
  try {
    const meta = await api("/api/meta");
    state.meta = meta;
    setLabels(meta.labels || { capabilities: {}, incident_types: {} });   // an older API without labels still works
    const badge = $("graph-badge");
    badge.textContent = `graph ${meta.graph}: ${Object.values(meta.counts.nodes).reduce((a, b) => a + b, 0).toLocaleString()} nodes`;
    badge.hidden = false;
    const sel = $("itype");
    meta.incident_types.forEach((t) => {
      const o = document.createElement("option");
      o.value = t;
      o.textContent = typeLabel(t);
      sel.appendChild(o);
    });
    await ready;
    setMeta(meta);
    await refreshHazards();
    await refreshClosures();
  } catch (e) {
    setStatus(e.message || "Could not load the graph. Start FalkorDB and reload.", "error");
  }
  document.querySelectorAll(".preset").forEach((b) => b.addEventListener("click", () => pickPreset(b.dataset.preset)));
  $("take").addEventListener("click", takeCall);
  $("close-toggle").addEventListener("click", () => setCloseMode(!state.closeMode));
  setInterval(renderClosures, 5000);                       // keep the "reopens in" countdown fresh
  $("graph-only").addEventListener("change", applyMode);
  $("text").addEventListener("input", clearPreset);
  $("why-toggle").addEventListener("click", () => openDrawer($("why").dataset.open !== "true"));
  const legend = $("legend");
  const setLegend = (open) => { legend.dataset.open = String(open); $("legend-toggle").setAttribute("aria-expanded", String(open)); };
  setLegend(!window.matchMedia("(max-width: 759px)").matches);   // collapsed on mobile, open on desktop
  $("legend-toggle").addEventListener("click", () => setLegend(legend.dataset.open !== "true"));
  applyMode();
}

start();
