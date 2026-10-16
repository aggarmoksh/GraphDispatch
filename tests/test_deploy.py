"""Phase 6A: self-healing demo state, safe client IP, and the deployment files. Zero Bedrock calls."""
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from starlette.requests import Request

from graphdispatch import api, db, llm
from graphdispatch.ops import add_hazard, dispatch, expire_stale, recall, run_call, why

ROOT = Path(__file__).resolve().parent.parent
client = TestClient(api.app)
LAT, LON = 37.3450, -121.8800


def statuses():
    return dict(db.read("unit_statuses"))


def open_ids():
    return [r[0] for r in db.read("open_incidents")]


# ---------------------------------------------------------------- expiry with a fake clock
def test_expire_stale_frees_units_keeps_memory_and_leaves_young_incidents():
    now = int(time.time())
    seed = statuses()
    old = run_call("caller-old", "10 Old Street", LAT, LON, "structure_fire", now=now - 40 * 60)
    add_hazard("10 Old Street", "oxygen_storage", "old hazard", now - 50 * 60, now + 86400, incident_id=old["incident_id"], now=now - 40 * 60)
    dispatch(old["decision_id"])
    assigned = {u["unit_id"] for u in old["recommendation"]["units"]}
    assert all(statuses()[u] == "assigned" for u in assigned)
    young = run_call("caller-young", "20 Young Street", 37.3601, -121.8553, "burn", now=now - 5 * 60)

    expired, freed = expire_stale(now=now)                    # default window: 30 minutes
    assert (expired, freed) == (1, len(assigned))
    assert statuses() == seed                                 # every unit is back to its seed status
    assert old["incident_id"] not in open_ids() and young["incident_id"] in open_ids()
    assert why(old["decision_id"])["incident"]["status"] == "expired"
    assert why(young["decision_id"])["incident"]["status"] == "open"
    # memory is kept: the decision still reads back and the hazard is still recalled at the same address
    again = run_call("caller-again", "10 Old St.", LAT, LON, "structure_fire", now=now)
    assert [h["kind"] for h in recall(again["incident_id"], now)["hazards"]] == ["oxygen_storage"]
    assert expire_stale(now=now) == (0, 0)                    # nothing left to expire that is old enough


def test_expire_window_is_configurable(monkeypatch):
    now = int(time.time())
    young = run_call("caller-y", "20 Young Street", 37.3601, -121.8553, "burn", now=now - 5 * 60)
    assert expire_stale(now=now) == (0, 0)
    monkeypatch.setenv("DEMO_EXPIRE_MIN", "2")
    assert expire_stale(now=now) == (1, 0)
    assert young["incident_id"] not in open_ids()
    other = run_call("caller-z", "30 Z Street", 37.3601, -121.8553, "burn", now=now - 60)
    assert expire_stale(now=now, expire_min=0.5) == (1, 0)     # explicit argument beats the environment
    assert other["incident_id"] not in open_ids()


def test_background_sweep_runs_at_startup(monkeypatch):
    monkeypatch.setenv("DEMO_EXPIRY_INTERVAL_S", "3600")
    now = int(time.time())
    stale = run_call("caller-s", "10 Old Street", LAT, LON, "structure_fire", now=now - 3 * 3600)
    assert stale["incident_id"] in open_ids()
    with TestClient(api.app) as c:                             # entering the context runs the lifespan task
        for _ in range(50):
            if stale["incident_id"] not in open_ids():
                break
            time.sleep(0.1)
        assert stale["incident_id"] not in open_ids()
        assert c.get("/api/health").status_code == 200


# ---------------------------------------------------------------- client IP
def fake_request(headers=None, peer="198.51.100.9"):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw, "client": (peer, 1234), "query_string": b""})


def test_strip_port():
    assert api._strip_port("203.0.113.7:51234") == "203.0.113.7"
    assert api._strip_port("203.0.113.7") == "203.0.113.7"
    assert api._strip_port("[2001:db8::7]:443") == "2001:db8::7"
    assert api._strip_port("2001:db8::7") == "2001:db8::7"


def test_client_ip_rules(monkeypatch):
    spoof = {"x-forwarded-for": "1.1.1.1, 2.2.2.2, 9.9.9.9"}
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    assert api.client_ip(fake_request(spoof)) == "198.51.100.9"            # headers ignored by default
    monkeypatch.setenv("TRUST_PROXY", "1")
    assert api.client_ip(fake_request(spoof)) == "9.9.9.9"                  # rightmost, never the leftmost
    assert api.client_ip(fake_request({**spoof, "cloudfront-viewer-address": "203.0.113.7:51234"})) == "203.0.113.7"
    assert api.client_ip(fake_request({"cloudfront-viewer-address": "[2001:db8::7]:443"})) == "2001:db8::7"
    assert api.client_ip(fake_request()) == "198.51.100.9"                  # no headers: the socket peer


def canned(incident_type="stroke"):
    def fake(system, messages, tools=None, max_tokens=300, force_tool=None, model_id=None):
        return {"tool_name": "classify_call", "text": "", "stop_reason": "tool_use", "input_tokens": 1, "output_tokens": 1,
                "latency_ms": 1.0, "tool_input": {"incident_type": incident_type, "hazards": [], "address_label": None,
                                                  "confidence": 0.95, "reason": "canned"}}
    return fake


def test_spoofed_leftmost_forwarded_for_cannot_change_the_counted_ip(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DAILY_FILE", tmp_path / "daily.json")
    monkeypatch.setenv("LLM_DAILY_CAP", "1000")
    monkeypatch.setenv("TRUST_PROXY", "1")
    monkeypatch.setattr(llm, "converse", canned())
    api._ip_calls.clear()
    codes = []
    for i in range(7):   # a new fake leftmost entry on every request, the same real (rightmost) address
        r = client.post("/api/call", json={"text": "face drooping", "lat": 37.33, "lon": -121.93},
                        headers={"X-Forwarded-For": f"10.{i}.0.1, 9.9.9.9"})
        codes.append(r.status_code)
    assert codes == [200] * 6 + [429]
    assert set(api._ip_calls) == {"9.9.9.9"}
    # a different real address is counted separately
    other = client.post("/api/call", json={"text": "face drooping", "lat": 37.33, "lon": -121.93}, headers={"X-Forwarded-For": "1.1.1.1, 8.8.8.8"})
    assert other.status_code == 200 and "8.8.8.8" in api._ip_calls


def test_proxy_headers_ignored_when_trust_proxy_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DAILY_FILE", tmp_path / "daily.json")
    monkeypatch.setenv("LLM_DAILY_CAP", "1000")
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    monkeypatch.setattr(llm, "converse", canned())
    api._ip_calls.clear()
    codes = [client.post("/api/call", json={"text": "face drooping", "lat": 37.33, "lon": -121.93},
                         headers={"X-Forwarded-For": f"10.{i}.0.1"}).status_code for i in range(7)]
    assert codes == [200] * 6 + [429]                          # rotating the header buys nothing
    assert set(api._ip_calls) == {"testclient"}


# ---------------------------------------------------------------- deployment files
def tracked():
    """Files git tracks or would track (not ignored), so the check also works before the commit."""
    return subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.split()


def find_bash():
    """A working POSIX bash (on Windows, Git Bash; the System32 bash.exe is WSL and is skipped)."""
    git = shutil.which("git")
    cands = [shutil.which("bash")]
    if git:
        cands.append(str(Path(git).resolve().parent.parent / "bin" / "bash.exe"))
        cands.append(str(Path(git).resolve().parent.parent.parent / "bin" / "bash.exe"))
    for c in cands:
        if c and Path(c).exists():
            try:
                r = subprocess.run([c, "-c", "echo ok"], capture_output=True, text=True, timeout=20)
                if r.stdout.strip() == "ok":
                    return c
            except Exception:
                pass
    return None


def test_iam_policy_allows_only_invoke_on_haiku_45():
    pol = json.loads((ROOT / "deploy" / "iam-bedrock-policy.json").read_text(encoding="utf-8"))
    assert pol["Version"] == "2012-10-17" and len(pol["Statement"]) == 1
    st = pol["Statement"][0]
    assert st["Effect"] == "Allow" and st["Action"] == "bedrock:InvokeModel"
    assert set(st) == {"Sid", "Effect", "Action", "Resource"}
    res = st["Resource"]
    assert "arn:aws:bedrock:us-east-1:<ACCOUNT_ID>:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0" in res
    regions = {r.split(":")[3] for r in res if ":foundation-model/" in r}
    assert regions == {"us-east-1", "us-east-2", "us-west-2"}
    assert all(r.endswith("anthropic.claude-haiku-4-5-20251001-v1:0") for r in res) and "*" not in json.dumps(pol)


def test_compose_files():
    dc = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    fb, app = dc["services"]["falkordb"], dc["services"]["app"]
    digest = re.search(r"falkordb/falkordb@sha256:[0-9a-f]{64}", (ROOT / "seed" / "DATA.md").read_text(encoding="utf-8")).group(0)
    assert fb["image"] == digest                                # pinned, and recorded in seed/DATA.md
    assert "ports" not in fb and fb["mem_limit"] == "300m"
    assert fb["healthcheck"]["test"] == ["CMD", "redis-cli", "ping"]
    assert any(v.endswith(":/var/lib/falkordb/data") for v in fb["volumes"])
    assert app["env_file"] == ".env.server" and app["ports"] == ["80:8000"] and app["mem_limit"] == "450m"
    assert app["depends_on"]["falkordb"]["condition"] == "service_healthy" and app["restart"] == "unless-stopped"
    assert fb["restart"] == "unless-stopped"
    local = (ROOT / "docker-compose.local.yml").read_text(encoding="utf-8")
    assert "8080:8000" in local and "!override" in local


def test_no_secrets_or_env_files_are_tracked_or_in_the_image_context():
    files = tracked()
    assert ".env" not in files and ".env.server" not in files and ".env.server.example" in files
    example = (ROOT / ".env.server.example").read_text(encoding="utf-8")
    assert "AWS_ACCESS_KEY_ID" not in example and "AWS_SECRET" not in example and "TRUST_PROXY=0" in example
    assert "LLM_DAILY_CAP=150" in example and "BEDROCK_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0" in example
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for must in (".env", ".env.*", ".venv/", "data/", "runs/", "tests/", ".git/"):
        assert must in ignore
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in docker and "USER app" in docker
    assert not re.search(r"^(COPY|ADD)\s+.*(\.env|tests|data)\b", docker, re.M)
    entry = (ROOT / "deploy" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "scripts/load.py" in entry and "--workers 1" in entry and "--port 8000" in entry
    pat = re.compile(r"AKIA[0-9A-Z]{16}|aws_secret_access_key\s*=\s*\S|-----BEGIN [A-Z ]*PRIVATE KEY")
    for f in files:
        if f.startswith(("tests/", "graphdispatch/static/vendor/")) or not f.endswith((".py", ".md", ".sh", ".yml", ".json", ".txt", ".example", ".toml")):
            continue
        assert not pat.search((ROOT / f).read_text(encoding="utf-8", errors="ignore")), f


@pytest.mark.skipif(find_bash() is None, reason="needs a working bash")
def test_ship_script_dry_run_prints_commands_and_changes_nothing(tmp_path):
    env = {"HOST": "ec2-user@203.0.113.10", "KEY_FILE": "/keys/demo.pem", "PATH": __import__("os").environ["PATH"]}
    out = subprocess.run([find_bash(), "deploy/ship.sh"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    text = out.stdout
    assert "DRY RUN" in text and "SHIPPING" not in text
    for cmd in ("git archive", "scp ", "tar -xzf", "ln -sfn", "docker compose up -d --build", "/api/health"):
        assert cmd in text, cmd
    short = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    assert not list(Path(tmp_path.anchor).glob(f"tmp/graphdispatch-{short}.tar.gz"))   # the dry run created no tarball
    script = (ROOT / "deploy" / "ship.sh").read_text(encoding="utf-8")
    assert "scp" in script and not re.search(r"scp[^\n]*\.env", script)       # no env file is ever copied from this machine
    assert "--yes" in script
