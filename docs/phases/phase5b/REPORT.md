# Phase 5B Report: UI polish

No graph query, seed logic or Bedrock call changed or was made in this phase. Units, incidents and callers are synthetic.

## What changed, per item
1. **Map follows the decision.** Every decision render (new call, history chip, after dispatch) fits the map to the incident, every station used, the chosen hospital, the nearest skipped hospital and every route point. Padding clears the legend and controls (desktop left 210 px, mobile left 64 px, plus top, right and bottom room). Verified in code: 0 decision points outside the map view in all 8 checked views.
2. **Legend.** Compact vertical list at top left on desktop (7 items, including chosen hospital and the skipped ring); a collapsible "Key" button on mobile, collapsed by default. No marker of the current decision sits under it in any checked view.
3. **Skipped hospital on the map.** The nearest skipped hospital gets a grey ring and a label, for example "Nearest, skipped: no clot removal" (S1) or "Nearest, skipped: no burn center" (burn). The chosen hospital is a larger filled blue marker; other hospitals are outlined, plain markers. The label flips to the left side if it would leave the map.
4. **One location marker.** The caller pin turns into the incident ring when a decision shows, and placing a new caller removes the old ring and routes. The check found exactly 1 location marker in every view.
5. **Plain language.** seed/capability_labels.csv and seed/incident_type_labels.csv (served in /api/meta as `labels`). The panel, tooltips, history chips and the incident type menu use labels (Paramedic (ALS), Ambulance transport, Fire attack, Clot removal (thrombectomy), and so on). The Why drawer keeps raw ids.
6. **m:ss times.** Panel times read like 9:11, 2:12, 0:49. The Why drawer keeps seconds and milliseconds.
7. **Rule text from numbers.** The API parses the sentence rules.py writes into a `rule` object (kind, extra seconds, limits, total, source); the panel renders, for S1: "Regional is 8:22 farther than O'Connor. AHA stroke guidance allows up to 30:00 extra to reach clot removal, so the patient goes to Regional." with "Source: AHA Mission: Lifeline Stroke EMS algorithm" as a small line. Other rule kinds also render in plain language. The full rule_applied string stays in the Why drawer.
8. **Skipped list.** "O'Connor Hospital, 0:49 away: no clot removal (nearest)".
9. **Visual check re-run** (graph only, sjfd_test, my own server on port 8001; the script refuses any other graph).
10. **Tests.** 61 pass (56 earlier plus 5 new in tests/test_labels.py): every capability id in the graph and every incident type has a label; /api/meta serves labels; parse_rule on the real output of rules.stroke_bypass for all three branches and the other sentence kinds; the S1 payload carries the structured rule.

## Tests and call log
61 passed, 0 failed. runs/llm_calls.log: 24 lines before pytest, 24 after (the 24 includes the operator's own calls; this phase made none).

## Screenshots (docs/phases/phase5/screens/, 0.9 MB total, old files replaced)
| file | shows |
|---|---|
| 01-s1-desktop.png | 1440x900, stroke west side: O'Connor ringed with "Nearest, skipped: no clot removal", filled Regional, red and blue routes fully in view, legend top left clear, panel with labels and m:ss, rule sentence with source line |
| 02-s1-mobile.png | 390x844, same call: map on top with the collapsed "Key" button, skipped label, both routes in view |
| 03-s1-mobile-full.png | 390x844 full page: map, call box, panel stacked, no horizontal scroll |
| 04-burn-desktop.png | burn east side: one location marker (the incident ring), "Nearest, skipped: no burn center" |
| 05-burn-mobile.png | burn on mobile, one location marker |
| 06-oxygen-call1-desktop.png | oxygen preset, garage fire: HM26 "added by oxygen storage", yellow hazard diamond beside the ring, crew note |
| 07-oxygen-call2-desktop.png | oxygen preset, collapse next door: hospital route and the remembered hazard |
| 08-oxygen-call2-mobile.png | same on mobile |
| 09-why-drawer-desktop.png | Why drawer on the eta query with real Cypher, raw seconds/ms and the list of queries |
| check.json | the machine check results below |

## Automated checks (docs/phases/phase5/screens/check.json), all 8 views OK
- Console errors: 0; page errors: 0; unexpected network hosts: none (localhost, tiles.openfreemap.org, Google Fonts only).
- Horizontal scroll: none at 1440 or 390 (scrollWidth equals innerWidth).
- Decision points outside the map view: 0; markers under the legend: 0; skipped label inside the map and clear of the legend (S1 and burn, both viewports).
- Raw capability or hazard ids in the panel text: none; "N s" second values in the panel text: none. The Why drawer still shows seconds and algo.SPpaths.

## Flags
- The operator's server on port 8000 (graph sjfd) was already running with old API code. The new page needs a restart of that server (python -m uvicorn graphdispatch.api:app --port 8000); I did not touch it. A last small change made the page fall back gracefully if labels or the rule object are missing (tests pass; not re-photographed).
- My first screenshot attempt reached the operator's server by accident (no calls were made, it failed at page load); the script now takes SCREENSHOT_URL and refuses any graph other than sjfd_test.
- The rule object comes from parsing a sentence (structured numbers are not stored); tests guard the format. POSTLAUNCH lists storing it properly.
- On a phone the incident ring, the skipped hospital marker and its label can sit close together (S1 mobile); they stay legible.
- Hospital markers are at the snapped road intersection, so the grey ring is up to about 150 m from the building.

## Not done
No new endpoints, no deployment, no closures or mutual aid, no graph or seed logic change, no Bedrock calls, no reset --yes on sjfd, no git remote or push. Planning files untouched. The operator's server was not stopped.
