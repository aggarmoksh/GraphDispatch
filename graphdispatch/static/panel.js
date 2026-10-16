// Decision panel and Why drawer. All server text is inserted with textContent, never as HTML.
// The panel speaks plain language (labels, m:ss); the Why drawer keeps raw ids, seconds and Cypher.
const KW = new Set(["MATCH", "OPTIONAL", "WHERE", "WITH", "RETURN", "CALL", "YIELD", "ORDER", "BY", "UNWIND", "AS", "LIMIT",
  "AND", "OR", "NOT", "IN", "IS", "NULL", "CASE", "WHEN", "THEN", "ELSE", "END", "DISTINCT", "SET", "MERGE", "CREATE", "ON", "DETACH", "DELETE"]);

export const QUERY_INFO = {
  unit_candidates: "Which available units hold the needed capabilities, where they are based, and the road intersection of that station.",
  eta: "Travel time in seconds along the cheapest road path between two intersections, computed inside FalkorDB by algo.SPpaths.",
  effective_requirements: "What the incident needs: the incident type's requirements plus anything added by active hazards at the same address, counted once per hazard kind.",
  hospitals: "Every hospital with its road intersection, the capabilities it offers and its designation levels.",
  dest_capability: "Which capability the destination hospital must offer for this incident type, and the stroke bypass limits when they apply.",
  recall_hazards: "Hazards at this address that are active right now, with the crew note for each kind.",
  recall_incidents: "Earlier incidents at the same normalized address in the last 30 days.",
  route: "The ordered road intersections of the cheapest path, drawn on the map.",
  why: "Everything recorded for this decision, read back in one query.",
  close_road: "Closing a road retypes its ROAD edges to CLOSED_ROAD with the same properties, so algo.SPpaths over ROAD skips them; the Closure node records why and when.",
  reopen_road: "Reopening retypes the CLOSED_ROAD edges back to ROAD with the original travel time, length and name.",
  nearest_road_segment: "The open road segment whose midpoint is nearest to the clicked point.",
  route_all: "The cheapest path ignoring closures (over ROAD and CLOSED_ROAD), with the closures it passes through. The difference from the real path is the detour.",
  eta_all: "Travel time ignoring closures, used to show what the closure cost and which unit would have gone without it.",
  decision_rerouted: "Records, per leg, which closure the decision had to route around and the extra seconds.",
  active_closure_count: "How many closures are active; the closure comparison only runs when there is at least one."
};

// ---------------------------------------------------------------- plain-language helpers (exported for the map and app)
let LABELS = { capabilities: {}, incident_types: {} };
export const setLabels = (l) => { LABELS = l; };
const sentence = (s) => { const t = String(s).replace(/_/g, " "); return t.charAt(0).toUpperCase() + t.slice(1); };
export const capLabel = (id) => LABELS.capabilities[id] || sentence(id);
export const typeLabel = (id) => LABELS.incident_types[id] || sentence(id);
export const hazardLabel = (id) => sentence(id);
/** Short noun phrase, e.g. "Clot removal (thrombectomy)" -> "clot removal". */
export const capShort = (id) => capLabel(id).replace(/\s*\(.*\)\s*$/, "").toLowerCase();
/** "Regional Medical Center of San Jose" -> "Regional"; "O'Connor Hospital" -> "O'Connor". */
export const shortName = (n) => n.replace(/\s+(Medical Center|Hospital)\b.*$/, "");
/** Seconds to m:ss (551 -> 9:11). */
export const mmss = (s) => { const t = Math.round(s); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
/** Plain reason a hospital was skipped, from the recorded reason text. */
export function skipText(reason) {
  const m = /lacks (\w+)/.exec(reason);
  if (m) return `no ${capShort(m[1])}` + (/\(nearest\)/.test(reason) ? " (nearest)" : "");
  return "too far under the stroke guidance limit";
}
/** Reason text for a unit's requirement: "required by incident type" or "added by oxygen storage". */
export function whyRequired(reasonText) {
  return reasonText.replace(/added by (\w+)/g, (_, k) => `added by ${hazardLabel(k).toLowerCase()}`);
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function qbutton(text, query, ctx, cls = "") {
  const b = el("button", "qline " + cls, text);
  b.type = "button";
  b.dataset.q = query;
  b.title = "Show the Cypher query for this line";
  b.addEventListener("click", () => ctx.onWhy(query, b));
  return b;
}

export function highlight(cypher) {
  const pre = el("pre", "cypher");
  pre.tabIndex = 0;
  const re = /(\$\w+)|(\b[A-Za-z_]+\b)/g;
  let last = 0, m;
  while ((m = re.exec(cypher))) {
    if (m.index > last) pre.appendChild(document.createTextNode(cypher.slice(last, m.index)));
    if (m[1]) pre.appendChild(el("span", "par", m[1]));
    else if (KW.has(m[2].toUpperCase())) pre.appendChild(el("span", "kw", m[2]));
    else pre.appendChild(document.createTextNode(m[2]));
    last = re.lastIndex;
  }
  pre.appendChild(document.createTextNode(cypher.slice(last)));
  return pre;
}

/** Rule sentence built from the rule numbers. Returns [text, sourceLine|null]. */
export function ruleText(p) {
  const r = p.rule || { kind: "other", text: p.rule_applied };
  const lim = (s) => mmss(s);
  switch (r.kind) {
    case "bypass_used":
      return [r.extra > 0
        ? `${shortName(r.capable)} is ${mmss(r.extra)} farther than ${shortName(r.fallback)}. AHA stroke guidance allows up to ${lim(r.max_extra)} extra to reach ${capShort("stroke_thrombectomy")}, so the patient goes to ${shortName(r.capable)}.`
        : `${shortName(r.capable)} is no farther than ${shortName(r.fallback)} and offers ${capShort("stroke_thrombectomy")}, so the patient goes to ${shortName(r.capable)}.`, r.source];
    case "bypass_declined_extra":
      return [`${shortName(r.capable)} is ${mmss(r.extra)} farther than ${shortName(r.fallback)}. AHA stroke guidance allows up to ${lim(r.max_extra)} extra, so the patient goes to ${shortName(r.fallback)}.`, r.source];
    case "bypass_declined_total":
      return [`${shortName(r.capable)} would take ${mmss(r.total)} in total, over the ${lim(r.max_total)} limit, so the patient goes to ${shortName(r.fallback)}.`, r.source];
    case "fastest":
      return [`Closest hospital with ${capShort(r.capability)}: ${shortName(r.hospital)}, ${mmss(r.eta)} away.`, null];
    case "no_destination":
      return ["No hospital is needed for this incident type.", null];
    case "none_offer":
      return [`No hospital offers ${capShort(r.capability)}.`, null];
    default:
      return [r.text, null];
  }
}

export function renderDecision(root, p, ctx) {
  root.replaceChildren();
  const inc = p.incident;
  const where = inc.address.startsWith("device@") ? `caller location ${inc.address.slice(7).replace(",", ", ")}` : inc.address;
  root.appendChild(el("p", "dsum", `${typeLabel(inc.type)} at ${where}`));
  root.appendChild(el("p", "sub", `Status: ${inc.status}. Synthetic incident ${inc.incident_id}.`));

  if (p.classification) {
    const c = p.classification;
    const hz = c.hazards.length ? c.hazards.map((h) => hazardLabel(h).toLowerCase()).join(", ") : "none";
    root.appendChild(el("p", "note", `The model read this call as ${typeLabel(c.incident_type).toLowerCase()}; hazards the caller reported: ${hz}.`
      + (c.model_note ? ` Model note: ${c.model_note}` : "")));
  }

  // units
  const us = el("div", "sect fireline");
  us.appendChild(el("h3", null, "Units to send (synthetic)"));
  if (p.units.length) {
    const t = el("table", "units");
    const head = el("tr");
    ["Unit", "Covers", "Time", "Why required"].forEach((h) => head.appendChild(el("th", null, h)));
    t.appendChild(head);
    p.units.forEach((u) => {
      const r = el("tr");
      const c1 = el("td"); c1.appendChild(qbutton(u.unit_id, "unit_candidates", ctx, "mono"));
      const c2 = el("td"); c2.appendChild(qbutton(capLabel(u.capability), "unit_candidates", ctx));
      const c3 = el("td"); c3.appendChild(qbutton(mmss(u.eta_s), "eta", ctx, "mono"));
      const c4 = el("td"); c4.appendChild(qbutton(whyRequired(u.reason_text), "effective_requirements", ctx));
      r.append(c1, c2, c3, c4);
      t.appendChild(r);
    });
    us.appendChild(t);
  } else {
    us.appendChild(el("p", "note", "No units are available for this incident."));
  }
  p.unmet.forEach((m) => {
    const line = el("p", "note");
    line.appendChild(qbutton(`UNMET: ${capLabel(m.capability)} (${whyRequired(m.reason_text)}). No available unit has it.`, "effective_requirements", ctx, "block unmet"));
    us.appendChild(line);
  });
  root.appendChild(us);

  // destination
  const hs = el("div", "sect medline");
  hs.appendChild(el("h3", null, "Destination hospital"));
  if (p.destination) {
    const d = p.destination;
    const lvl = d.level ? `, level ${d.level}` : "";
    hs.appendChild(qbutton(`${d.name}${lvl}, ${mmss(d.eta_s)} away`, "hospitals", ctx, "block"));
    p.skipped.forEach((s) => hs.appendChild(qbutton(`${s.name}, ${mmss(s.eta_s)} away: ${skipText(s.reason)}`, "hospitals", ctx, "block skip")));
  }
  const [rule, source] = ruleText(p);
  hs.appendChild(qbutton(rule, "dest_capability", ctx, "block rule"));
  if (source) hs.appendChild(el("p", "source", `Source: ${source}`));
  root.appendChild(hs);

  // road closures: rerouting, what would have changed, and legs with no route
  const cl = p.rerouted || [], ch = p.changes || { units: [], hospital: null }, nr = p.no_route || [];
  if (cl.length || ch.units.length || ch.hospital || nr.length) {
    const cs = el("div", "sect closureline");
    cs.appendChild(el("h3", null, "Road closures"));
    cl.forEach((x) => {
      cs.appendChild(qbutton(`Rerouted around ${x.name || "a closed road"} (synthetic closure): +${mmss(x.extra_s)}`, "route_all", ctx, "block"));
      const legText = x.leg === "hospital" ? "on the way to the hospital" : `for unit ${x.leg}`;
      cs.appendChild(qbutton(`${legText}; closure reason: ${x.reason || "synthetic"}`, "close_road", ctx, "block sub closure-sub"));
    });
    ch.units.forEach((c) => cs.appendChild(qbutton(`Without the closure, ${c.without.join(", ")} would have gone (${capLabel(c.capability)})`, "eta_all", ctx, "block")));
    if (ch.hospital) cs.appendChild(qbutton(`Without the closure, the patient would have gone to ${ch.hospital.without}`, "eta_all", ctx, "block"));
    nr.forEach((leg) => cs.appendChild(qbutton(`No route: ${leg}`, "eta", ctx, "block unmet")));
    root.appendChild(cs);
  }

  // memory
  if (p.recalled_hazard_groups.length || p.recalled_incidents.length) {
    const ms = el("div", "sect hazline");
    ms.appendChild(el("h3", null, "Memory of this address"));
    p.recalled_hazard_groups.forEach((g) => {
      const head = g.count > 1 ? `${hazardLabel(g.kind)} x${g.count}` : hazardLabel(g.kind);
      ms.appendChild(qbutton(`${head}: ${g.notes.filter(Boolean).join("; ")}`, "recall_hazards", ctx, "block"));
      if (g.crew_note) ms.appendChild(qbutton(`Crew note: ${g.crew_note}`, "recall_hazards", ctx, "block"));
    });
    p.recalled_incidents.forEach((i) => ms.appendChild(qbutton(`Earlier incident here: ${typeLabel(i.type).toLowerCase()} (${i.incident_id})`, "recall_incidents", ctx, "block")));
    root.appendChild(ms);
  }

  // actions
  const actions = el("div", "actions");
  const open = inc.status === "open";
  const disp = el("button", "primary", inc.status === "dispatched" ? "Dispatched" : "Dispatch these units");
  disp.type = "button";
  disp.disabled = !open || !p.units.length;
  disp.addEventListener("click", () => ctx.onDispatch(p));
  const clr = el("button", "plain", "Clear incident");
  clr.type = "button";
  clr.disabled = inc.status === "cleared";
  clr.addEventListener("click", () => ctx.onClear(p));
  actions.append(disp, clr);
  root.appendChild(actions);
}

export function renderWhy(body, p, name) {
  body.replaceChildren();
  const runs = p.queries.filter((q) => q.name === name);
  const left = el("div");
  const total = runs.reduce((a, q) => a + q.ms, 0);
  left.appendChild(el("h3", null, `${name}  ${runs.length ? `(${runs.length} run${runs.length > 1 ? "s" : ""}, ${total.toFixed(1)} ms)` : "(not run for this decision)"}`));
  left.appendChild(el("p", "sub", QUERY_INFO[name] || ""));
  const q = runs[0] || p.queries.find((x) => x.name === name);
  if (q) left.appendChild(highlight(q.cypher));
  if (runs.length) {
    const ul = el("ul", "runs");
    runs.slice(0, 12).forEach((r) => {
      const ps = Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(", ") || "no parameters";
      ul.appendChild(el("li", null, `${r.ms.toFixed(2)} ms  ${ps}`));
    });
    if (runs.length > 12) ul.appendChild(el("li", null, `and ${runs.length - 12} more runs`));
    left.appendChild(ul);
  }
  if (name === "dest_capability" || name === "hospitals") {
    left.appendChild(el("p", "sub", `Full rule text recorded for this decision: ${p.rule_applied}`));
  }
  const right = el("div");
  const sum = p.queries.reduce((a, x) => a + x.ms, 0);
  right.appendChild(el("h3", null, `All queries for this call: ${p.queries.length}, ${sum.toFixed(1)} ms`));
  const list = el("ul", "qlist");
  const seen = [];
  p.queries.forEach((x) => { if (!seen.includes(x.name)) seen.push(x.name); });
  seen.forEach((n) => {
    const rs = p.queries.filter((x) => x.name === n);
    const li = el("li");
    const b = el("button");
    b.type = "button";
    b.setAttribute("aria-current", String(n === name));
    b.append(el("span", null, rs.length > 1 ? `${n} (x${rs.length})` : n), el("span", "ms", `${rs.reduce((a, x) => a + x.ms, 0).toFixed(1)} ms`));
    b.addEventListener("click", () => renderWhy(body, p, n));
    li.appendChild(b);
    list.appendChild(li);
  });
  right.appendChild(list);
  body.append(left, right);
}
