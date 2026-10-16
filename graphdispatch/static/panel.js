// Decision panel and Why drawer. All server text is inserted with textContent, never as HTML.
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
};

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

const human = (s) => { const t = String(s).replace(/_/g, " "); return t.charAt(0).toUpperCase() + t.slice(1); };
const secs = (n) => `${Math.round(n)} s`;

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

export function renderDecision(root, p, ctx) {
  root.replaceChildren();
  const inc = p.incident;
  const where = inc.address.startsWith("device@") ? `caller location ${inc.address.slice(7).replace(",", ", ")}` : inc.address;
  root.appendChild(el("p", "dsum", `${human(inc.type)} at ${where}`));
  root.appendChild(el("p", "sub", `Status: ${inc.status}. Synthetic incident ${inc.incident_id}.`));

  if (p.classification) {
    const c = p.classification;
    const hz = c.hazards.length ? c.hazards.map(human).join(", ").toLowerCase() : "none";
    root.appendChild(el("p", "note", `The model read this call as ${c.incident_type.replace(/_/g, " ")}; hazards the caller reported: ${hz}.`
      + (c.model_note ? ` Model note: ${c.model_note}` : "")));
  }

  // units
  const us = el("div", "sect fireline");
  us.appendChild(el("h3", null, "Units to send (synthetic)"));
  if (p.units.length) {
    const t = el("table", "units");
    const head = el("tr");
    ["Unit", "Covers", "ETA", "Why required"].forEach((h) => head.appendChild(el("th", null, h)));
    t.appendChild(head);
    p.units.forEach((u) => {
      const r = el("tr");
      const c1 = el("td"); const b1 = qbutton(u.unit_id, "unit_candidates", ctx, "mono"); c1.appendChild(b1);
      const c2 = el("td"); c2.appendChild(qbutton(u.capability.replace(/_/g, " "), "unit_candidates", ctx));
      const c3 = el("td"); c3.appendChild(qbutton(secs(u.eta_s), "eta", ctx, "mono"));
      const c4 = el("td"); c4.appendChild(qbutton(u.reason_text, "effective_requirements", ctx));
      r.append(c1, c2, c3, c4);
      t.appendChild(r);
    });
    us.appendChild(t);
  } else {
    us.appendChild(el("p", "note", "No units are available for this incident."));
  }
  p.unmet.forEach((m) => {
    const line = el("p", "note");
    line.appendChild(qbutton(`UNMET: ${m.capability.replace(/_/g, " ")} (${m.reason_text}). No available unit has it.`, "effective_requirements", ctx, "block unmet"));
    us.appendChild(line);
  });
  root.appendChild(us);

  // destination
  const hs = el("div", "sect medline");
  hs.appendChild(el("h3", null, "Destination hospital"));
  if (p.destination) {
    const d = p.destination;
    const lvl = d.level ? `, level ${d.level}` : "";
    hs.appendChild(qbutton(`${d.name}${lvl}, ETA ${secs(d.eta_s)}`, "hospitals", ctx, "block"));
    p.skipped.forEach((s) => hs.appendChild(qbutton(`Skipped ${s.name} (${secs(s.eta_s)}): ${s.reason}`, "hospitals", ctx, "block")));
    hs.appendChild(qbutton(`Rule: ${p.rule_applied}`, "dest_capability", ctx, "block"));
  } else {
    hs.appendChild(qbutton(p.rule_applied.startsWith("no destination") ? "No hospital is needed for this incident type." : p.rule_applied, "dest_capability", ctx, "block"));
  }
  root.appendChild(hs);

  // memory
  if (p.recalled_hazard_groups.length || p.recalled_incidents.length) {
    const ms = el("div", "sect hazline");
    ms.appendChild(el("h3", null, "Memory of this address"));
    p.recalled_hazard_groups.forEach((g) => {
      const head = g.count > 1 ? `${human(g.kind)} x${g.count}` : human(g.kind);
      ms.appendChild(qbutton(`${head}: ${g.notes.filter(Boolean).join("; ")}`, "recall_hazards", ctx, "block"));
      if (g.crew_note) ms.appendChild(qbutton(`Crew note: ${g.crew_note}`, "recall_hazards", ctx, "block"));
    });
    p.recalled_incidents.forEach((i) => ms.appendChild(qbutton(`Earlier incident here: ${i.type.replace(/_/g, " ")} (${i.incident_id})`, "recall_incidents", ctx, "block")));
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
