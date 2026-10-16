import { api } from "/api.js";
import { initMap, setMeta, setCaller, setIncident, setHazards, drawRoutes, fitTo, ready } from "/map.js";
import { renderDecision, renderWhy } from "/panel.js";

const $ = (id) => document.getElementById(id);
const state = { meta: null, loc: null, preset: null, history: [], current: -1, busy: false };

const PRESETS = {
  stroke: { lat: 37.3300, lon: -121.9300, type: "stroke", addr: "",
    text: "My wife's face is drooping on one side and she can't lift her right arm, it started ten minutes ago" },
  burn: { lat: 37.3600, lon: -121.8550, type: "burn", addr: "",
    text: "A pot of oil caught fire, I put it out but my son's arm is badly burned and blistering" },
  oxygen: { lat: 37.3360, lon: -121.8900, type: "structure_fire", addr: "200 Demo Street",
    text: "Smoke coming out of the garage at 200 Demo Street, my neighbor uses home oxygen, please hurry",
    text2: "My neighbor at 200 Demo St just collapsed and isn't breathing" },
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
  setCaller(lat, lon);
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
    renderWhy($("why-body"), cur.payload, name);
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

async function present(payload, label) {
  state.history.push({ label, payload });
  state.current = state.history.length - 1;
  renderHistory();
  show(payload);
  await drawRoutes(inc_routes(payload));
  const pts = payload.routes.flatMap((r) => r.coords);
  fitTo([[payload.incident.lon, payload.incident.lat], ...pts]);
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

async function graphCall(type, address) {
  return api("/api/recommend", { method: "POST", body: { lat: state.loc.lat, lon: state.loc.lon, incident_type: type, address } });
}

async function takeCall() {
  if (!state.loc) { setStatus("Click the map to place a caller, or pick a preset.", "error"); return; }
  const graphOnly = $("graph-only").checked;
  await guarded(async () => {
    setStatus(graphOnly ? "Walking the graph…" : "Reading the call, then walking the graph…");
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
    await present(payload, `Call ${state.history.length + 1}: ${payload.incident.type.replace(/_/g, " ")}`);
    setStatus(`Recommendation ready in ${payload.total_ms} ms. Nothing is dispatched until you confirm.`, "ok");
  });
}

// ---------------------------------------------------------------- start
async function start() {
  initMap((lat, lon) => { if (!state.busy) { clearPreset(); setLoc(lat, lon); setStatus(""); } });
  try {
    const meta = await api("/api/meta");
    state.meta = meta;
    const badge = $("graph-badge");
    badge.textContent = `graph ${meta.graph}: ${Object.values(meta.counts.nodes).reduce((a, b) => a + b, 0).toLocaleString()} nodes`;
    badge.hidden = false;
    const sel = $("itype");
    meta.incident_types.forEach((t) => {
      const o = document.createElement("option");
      o.value = t;
      o.textContent = t.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
      sel.appendChild(o);
    });
    await ready;
    setMeta(meta);
    await refreshHazards();
  } catch (e) {
    setStatus(e.message || "Could not load the graph. Start FalkorDB and reload.", "error");
  }
  document.querySelectorAll(".preset").forEach((b) => b.addEventListener("click", () => pickPreset(b.dataset.preset)));
  $("take").addEventListener("click", takeCall);
  $("graph-only").addEventListener("change", applyMode);
  $("text").addEventListener("input", clearPreset);
  $("why-toggle").addEventListener("click", () => openDrawer($("why").dataset.open !== "true"));
  applyMode();
}

start();
