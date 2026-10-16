"""Visual check with Playwright (chromium).

Start a server on a FREE port with the test graph, for example:
  GRAPH_NAME=sjfd_test python -m uvicorn graphdispatch.api:app --port 8001
then:  SCREENSHOT_URL=http://localhost:8001/ python docs/phases/phase5/screenshots.py
The script refuses to run against a server whose graph is not sjfd_test.

Graph-only mode only: zero Bedrock calls. Checks, besides taking screenshots:
  console errors, off-origin requests, horizontal scroll, one location marker, plain-language panel text,
  the skipped hospital label, and that every point of the decision (routes, incident, stations, hospitals) is inside
  the map view and clear of the legend.
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "screens"
OUT.mkdir(exist_ok=True)
URL = os.environ.get("SCREENSHOT_URL", "http://localhost:8001/")
ALLOWED_HOSTS = {"localhost", "tiles.openfreemap.org", "fonts.googleapis.com", "fonts.gstatic.com"}
RAW_IDS = re.compile(r"\b(stroke_thrombectomy|fire_suppression|stroke_primary|pediatric_trauma|oxygen_storage|aggressive_dog)\b|\bals\b")
SECONDS = re.compile(r"\b\d+ s\b")

health = json.load(urllib.request.urlopen(URL + "api/health"))
if health.get("graph") != "sjfd_test":
    sys.exit(f"refusing to run: the server at {URL} uses graph {health.get('graph')!r}, not 'sjfd_test'")

console_errors, page_errors, hosts, failed = [], [], set(), []
report = {"checks": {}}

GEOMETRY_JS = """() => {
  const map = window.__gdMap, c = map.getContainer(), W = c.clientWidth, H = c.clientHeight;
  const cr = c.getBoundingClientRect();
  const inside = (x, y) => x >= 0 && y >= 0 && x <= W && y <= H;
  const pts = (window.__gdLastFit || []).map((p) => map.project(p));
  const outside = pts.filter((p) => !inside(p.x, p.y)).length;
  const lg = document.getElementById('legend').getBoundingClientRect();
  const hit = (r) => !(r.right < lg.left || r.left > lg.right || r.bottom < lg.top || r.top > lg.bottom);
  const rel = (r) => ({ l: r.left - cr.left, t: r.top - cr.top, r: r.right - cr.left, b: r.bottom - cr.top });
  const marks = [...document.querySelectorAll('.mk.hosp.chosen, .mk.hosp.skipped, .mk.pin, .mk.st.used, .mk.haz')];
  const rects = marks.map((m) => ({ cls: m.className, r: m.getBoundingClientRect() }));
  const label = document.querySelector('.mklabel:not([hidden])');
  const lr = label ? label.getBoundingClientRect() : null;
  return {
    points: pts.length, points_outside_view: outside,
    markers_outside_map: rects.filter((m) => { const r = rel(m.r); return r.l < 0 || r.t < 0 || r.r > W || r.b > H; }).map((m) => m.cls),
    markers_under_legend: rects.filter((m) => hit(m.r)).map((m) => m.cls),
    label_text: label ? label.textContent : null,
    label_inside_map: lr ? (rel(lr).l >= 0 && rel(lr).r <= W && rel(lr).t >= 0 && rel(lr).b <= H) : null,
    label_under_legend: lr ? hit(lr) : null,
    location_markers: document.querySelectorAll('.mk.caller, .mk.pin').length,
    chosen_hospitals: document.querySelectorAll('.mk.hosp.chosen').length,
  };
}"""


def watch(page):
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    page.on("request", lambda r: hosts.add(urlparse(r.url).hostname))
    page.on("requestfailed", lambda r: failed.append(f"{r.url[:90]} {r.failure}"))


def load(page):
    page.goto(URL)
    page.wait_for_selector(".mk.st")
    page.wait_for_function("document.querySelectorAll('.mk.st').length === 10 && document.querySelectorAll('.mk.hosp').length === 3")
    page.wait_for_load_state("networkidle")
    page.check("#graph-only")


def take(page, preset, wait_text):
    page.click(f'[data-preset="{preset}"]')
    page.click("#take")
    page.wait_for_selector("table.units", timeout=30000)
    page.wait_for_function(f"document.getElementById('status').textContent.includes('{wait_text}')", timeout=30000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)  # tiles and route layers settle


def shot(page, name, full=False):
    path = OUT / name
    if page.viewport_size["width"] < 760:
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
    page.screenshot(path=str(path), full_page=full)
    try:  # shrink with a palette (the map is flat-colored) to keep the repo small
        from PIL import Image
        Image.open(path).convert("RGB").quantize(colors=128, method=Image.Quantize.FASTOCTREE).save(path, optimize=True)
    except Exception as e:
        print("compress skipped:", e)
    print("saved", name, path.stat().st_size, "bytes")


def verify(page, key, expect_label=None, expect_one_marker=True):
    g = page.evaluate(GEOMETRY_JS)
    text = page.locator("#decision").inner_text()
    g["raw_ids_in_panel"] = sorted(set(m.group(0) for m in RAW_IDS.finditer(text)))
    g["seconds_in_panel"] = SECONDS.findall(text)
    g["scroll_w"] = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    ok = (g["points_outside_view"] == 0 and not g["markers_outside_map"] and not g["markers_under_legend"]
          and not g["raw_ids_in_panel"] and not g["seconds_in_panel"] and g["scroll_w"][0] <= g["scroll_w"][1]
          and (g["location_markers"] == 1 if expect_one_marker else True))
    if expect_label:
        ok = ok and g["label_text"] == expect_label and g["label_inside_map"] and not g["label_under_legend"]
    g["ok"] = ok
    report["checks"][key] = g
    print(key, "OK" if ok else "FAILED", json.dumps({k: v for k, v in g.items() if k != "ok"}))
    return ok


with sync_playwright() as p:
    browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    all_ok = True

    # ---- desktop 1440x900
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    watch(page)
    load(page)
    take(page, "stroke", "Recommendation ready")
    all_ok &= verify(page, "s1-desktop", expect_label="Nearest, skipped: no clot removal")
    report["s1_panel_text"] = page.locator("#decision").inner_text()
    shot(page, "01-s1-desktop.png")
    page.locator("table.units tr:nth-child(2) td:nth-child(3) button").click()   # a time cell -> eta query
    page.wait_for_selector("pre.cypher")
    page.wait_for_timeout(300)
    report["why_keeps_raw_seconds"] = bool(re.search(r"\d+\.\d+ ms", page.locator("#why-body").inner_text())) and "algo.SPpaths" in page.locator("pre.cypher").inner_text()
    shot(page, "09-why-drawer-desktop.png")
    page.click("#why-toggle")

    take(page, "burn", "Recommendation ready")
    all_ok &= verify(page, "burn-desktop")
    shot(page, "04-burn-desktop.png")

    take(page, "oxygen", "Both calls done")
    page.locator("#history button", has_text="Structure fire").last.click()
    page.wait_for_timeout(1200)
    all_ok &= verify(page, "oxygen-call1-desktop")
    report["hazard_diamonds"] = page.locator(".mk.haz").count()
    report["oxygen_call1_has_HM26"] = "HM26" in page.locator("#decision").inner_text()
    shot(page, "06-oxygen-call1-desktop.png")
    page.locator("#history button", has_text="Cardiac arrest").last.click()
    page.wait_for_timeout(1200)
    all_ok &= verify(page, "oxygen-call2-desktop")
    shot(page, "07-oxygen-call2-desktop.png")
    page.close()

    # ---- mobile 390x844
    page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    watch(page)
    load(page)
    take(page, "stroke", "Recommendation ready")
    all_ok &= verify(page, "s1-mobile", expect_label="Nearest, skipped: no clot removal")
    shot(page, "02-s1-mobile.png")
    shot(page, "03-s1-mobile-full.png", full=True)
    take(page, "burn", "Recommendation ready")
    all_ok &= verify(page, "burn-mobile")
    shot(page, "05-burn-mobile.png")
    take(page, "oxygen", "Both calls done")
    all_ok &= verify(page, "oxygen-call2-mobile")
    shot(page, "08-oxygen-call2-mobile.png")
    page.close()
    browser.close()

report["console_errors"] = console_errors
report["page_errors"] = page_errors
report["request_hosts"] = sorted(h for h in hosts if h)
report["unexpected_hosts"] = sorted(h for h in hosts if h and h not in ALLOWED_HOSTS)
report["failed_requests"] = failed
report["all_checks_ok"] = bool(all_ok)
(OUT / "check.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
print("console_errors", len(console_errors), "page_errors", len(page_errors), "unexpected_hosts", report["unexpected_hosts"],
      "why_keeps_raw_seconds", report.get("why_keeps_raw_seconds"), "all_checks_ok", all_ok)
sys.exit(0 if (all_ok and not console_errors and not page_errors and not report["unexpected_hosts"]) else 1)
