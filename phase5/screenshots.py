"""Visual check with Playwright (chromium). Server must be running on :8000 with GRAPH_NAME=sjfd_test.

Graph-only mode only: zero Bedrock calls. Records console errors, off-origin requests and horizontal scroll.
Run: python phase5/screenshots.py
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "screens"
OUT.mkdir(exist_ok=True)
URL = "http://localhost:8000/"
ALLOWED_HOSTS = {"localhost", "tiles.openfreemap.org", "fonts.googleapis.com", "fonts.gstatic.com"}

console_errors, page_errors, hosts, failed = [], [], set(), []
report = {}


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
    page.screenshot(path=str(path), full_page=full)
    try:  # shrink with a palette (the map is flat-colored) to keep the repo small
        from PIL import Image
        Image.open(path).convert("RGB").quantize(colors=128, method=Image.Quantize.FASTOCTREE).save(path, optimize=True)
    except Exception as e:
        print("compress skipped:", e)
    print("saved", name, path.stat().st_size, "bytes")


with sync_playwright() as p:
    browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])

    # ---- desktop 1440x900
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    watch(page)
    load(page)
    take(page, "stroke", "Recommendation ready")
    report["stroke_rows"] = page.locator("table.units tbody tr, table.units tr").count() - 1
    report["stroke_destination"] = page.locator(".medline .qline").first.inner_text()
    shot(page, "02-stroke-desktop.png")
    page.locator("table.units tr:nth-child(2) td:nth-child(3) button").click()   # an ETA cell -> eta query
    page.wait_for_selector("pre.cypher")
    page.wait_for_timeout(300)
    shot(page, "03-why-drawer-desktop.png")
    report["why_cypher_has_spp"] = "algo.SPpaths" in page.locator("pre.cypher").inner_text()

    page.click("#why-toggle")  # hide the drawer for the next shots
    take(page, "oxygen", "Both calls done")
    page.locator("#history button", has_text="structure fire").click()
    page.wait_for_timeout(1200)
    report["oxygen_call1_text"] = page.locator("#decision").inner_text()
    report["hazard_diamonds"] = page.locator(".mk.haz").count()
    shot(page, "04-oxygen-call1-desktop.png")
    page.locator("#history button", has_text="cardiac arrest").click()
    page.wait_for_timeout(1200)
    report["oxygen_call2_text"] = page.locator("#decision").inner_text()
    shot(page, "05-oxygen-call2-desktop.png")
    report["desktop_scroll_w"] = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    page.close()

    # ---- mobile 390x844
    page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    watch(page)
    load(page)
    take(page, "stroke", "Recommendation ready")
    report["mobile_scroll_w"] = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    page.evaluate("window.scrollTo(0, 0)")
    shot(page, "06-stroke-mobile.png")
    shot(page, "07-stroke-mobile-full.png", full=True)
    page.close()
    browser.close()

report["console_errors"] = console_errors
report["page_errors"] = page_errors
report["request_hosts"] = sorted(h for h in hosts if h)
report["unexpected_hosts"] = sorted(h for h in hosts if h and h not in ALLOWED_HOSTS)
report["failed_requests"] = failed
(OUT / "check.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in report.items() if k not in ("oxygen_call1_text", "oxygen_call2_text")}, indent=1))
sys.exit(1 if (console_errors or page_errors or report["unexpected_hosts"]) else 0)
