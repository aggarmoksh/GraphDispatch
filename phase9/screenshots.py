"""Visual check for road closures (Playwright, chromium). Graph-only: zero Bedrock calls.

Start a server on a FREE port with the test graph:  GRAPH_NAME=sjfd_test python -m uvicorn graphdispatch.api:app --port 8001
then:  SCREENSHOT_URL=http://localhost:8001/ python phase9/screenshots.py
Refuses any server whose graph is not sjfd_test. Saves to phase9/screens/ and writes check.json.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "screens"
OUT.mkdir(exist_ok=True)
URL = os.environ.get("SCREENSHOT_URL", "http://localhost:8001/")
ALLOWED = {"localhost", "tiles.openfreemap.org", "fonts.googleapis.com", "fonts.gstatic.com"}
health = json.load(urllib.request.urlopen(URL + "api/health"))
if health.get("graph") != "sjfd_test":
    sys.exit(f"refusing: server graph is {health.get('graph')!r}, not 'sjfd_test'")

console_errors, page_errors, hosts, report = [], [], set(), {"checks": {}}

GEOM = """() => {
  const map = window.__gdMap, c = map.getContainer(), W = c.clientWidth, H = c.clientHeight, cr = c.getBoundingClientRect();
  const lg = document.getElementById('legend').getBoundingClientRect();
  const hit = (r) => !(r.right < lg.left || r.left > lg.right || r.bottom < lg.top || r.top > lg.bottom);
  const inMap = (r) => r.left >= cr.left && r.right <= cr.right && r.top >= cr.top && r.bottom <= cr.bottom;
  const labels = [...document.querySelectorAll('.closedlabel')].map((e) => e.getBoundingClientRect());
  const pts = (window.__gdLastFit || []).map((p) => map.project(p));
  return { closed_labels: labels.length, labels_inside_map: labels.filter(inMap).length, labels_under_legend: labels.filter(hit).length,
           points_outside_view: pts.filter((p) => p.x < 0 || p.y < 0 || p.x > W || p.y > H).length,
           closure_list_items: document.querySelectorAll('#clo-list li button').length,
           location_markers: document.querySelectorAll('.mk.caller, .mk.pin').length };
}"""


def watch(page):
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    page.on("request", lambda r: hosts.add(urlparse(r.url).hostname))


def shot(page, name, full=False):
    path = OUT / name
    if page.viewport_size["width"] < 760:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
    page.screenshot(path=str(path), full_page=full)
    try:
        from PIL import Image
        Image.open(path).convert("RGB").quantize(colors=128, method=Image.Quantize.FASTOCTREE).save(path, optimize=True)
    except Exception as e:
        print("compress skipped:", e)
    print("saved", name, path.stat().st_size, "bytes")


def load(page):
    page.goto(URL)
    page.wait_for_function("document.querySelectorAll('.mk.st').length === 10 && document.querySelectorAll('.mk.hosp').length === 3")
    page.wait_for_load_state("networkidle")
    page.check("#graph-only")


def run_preset(page):
    page.click('[data-preset="closure"]')
    page.click("#take")
    page.wait_for_selector("table.units", timeout=30000)
    page.wait_for_function("document.getElementById('status').textContent.includes('Recommendation ready')", timeout=30000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)


def verify(page, key):
    g = page.evaluate(GEOM)
    text = page.locator("#decision").inner_text()
    g["rerouted_line"] = [ln for ln in text.splitlines() if ln.startswith("Rerouted around")]
    g["without_lines"] = [ln for ln in text.splitlines() if ln.startswith("Without the closure")]
    g["scroll_w"] = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    ok = (g["closed_labels"] == 2 and g["labels_inside_map"] == 2 and g["labels_under_legend"] == 0 and g["points_outside_view"] == 0
          and g["closure_list_items"] == 2 and g["location_markers"] == 1 and len(g["rerouted_line"]) >= 1 and "(synthetic closure): +" in g["rerouted_line"][0]
          and len(g["without_lines"]) >= 1 and g["scroll_w"][0] <= g["scroll_w"][1])
    g["ok"] = ok
    report["checks"][key] = g
    print(key, "OK" if ok else "FAILED", json.dumps(g))
    return ok


with sync_playwright() as p:
    browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    all_ok = True

    page = browser.new_page(viewport={"width": 1440, "height": 900})
    watch(page)
    load(page)
    run_preset(page)
    all_ok &= verify(page, "closure-desktop")
    report["panel_text_desktop"] = page.locator("#decision").inner_text()
    shot(page, "01-closure-desktop.png")
    page.locator(".closureline .qline", has_text="Rerouted around").first.click()           # opens the comparison route query
    page.wait_for_selector("pre.cypher")
    report["why_route_all_has_closed_road"] = "CLOSED_ROAD" in page.locator("pre.cypher").inner_text()
    shot(page, "02-why-drawer-closure-desktop.png")
    page.click("#why-toggle")
    # "Close a road" by clicking the map, then reopen it with its button
    page.click("#close-toggle")
    box = page.locator("#map").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.62, box["y"] + box["height"] * 0.45)
    page.wait_for_function("document.querySelectorAll('#clo-list li button').length === 3", timeout=15000)
    page.wait_for_timeout(800)
    report["third_closure_listed"] = True
    shot(page, "03-close-a-road-click-desktop.png")
    page.locator("#clo-list li button").last.click()
    page.wait_for_function("document.querySelectorAll('#clo-list li button').length === 2", timeout=15000)
    report["reopen_button_works"] = True
    page.close()

    page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    watch(page)
    load(page)
    run_preset(page)
    all_ok &= verify(page, "closure-mobile")
    shot(page, "04-closure-mobile.png")
    shot(page, "05-closure-mobile-full.png", full=True)
    page.close()
    browser.close()

report["console_errors"], report["page_errors"] = console_errors, page_errors
report["request_hosts"] = sorted(h for h in hosts if h)
report["unexpected_hosts"] = sorted(h for h in hosts if h and h not in ALLOWED)
report["all_checks_ok"] = bool(all_ok)
(OUT / "check.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
print("console_errors", len(console_errors), "page_errors", len(page_errors), "unexpected_hosts", report["unexpected_hosts"],
      "why_route_all_has_closed_road", report.get("why_route_all_has_closed_road"), "all_checks_ok", all_ok)
sys.exit(0 if (all_ok and not console_errors and not page_errors and not report["unexpected_hosts"]) else 1)
