"""Write requirements-runtime.txt: exact versions (from this venv) of the runtime dependency closure only.

Runtime needs the API, the LLM adapter, the loader (pandas) and the graph client. It does not need osmnx, networkx,
playwright, pillow, pytest, httpx or the MCP SDK. Run: python docs/phases/phase6a/make_runtime_reqs.py
"""
import re
from importlib import metadata
from pathlib import Path

ROOTS = ["falkordb", "python-dotenv", "boto3", "fastapi", "uvicorn", "jsonschema", "pandas"]
seen = {}


def norm(n):
    return re.sub(r"[-_.]+", "-", n).lower()


def walk(name):
    key = norm(name)
    if key in seen:
        return
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return
    seen[key] = f"{dist.metadata['Name']}=={dist.version}"
    for req in dist.requires or []:
        if "extra ==" in req:
            continue
        marker = req.split(";", 1)[1].strip() if ";" in req else ""
        if marker:
            try:
                from packaging.markers import Marker
                if not Marker(marker).evaluate({"extra": ""}):
                    continue
            except Exception:
                pass
        walk(re.split(r"[ ;<>=!~\[(]", req, 1)[0])


for r in ROOTS:
    walk(r)
lines = sorted(seen.values(), key=str.lower)
Path(__file__).resolve().parents[3].joinpath("requirements-runtime.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(len(lines), "pinned packages")
print("\n".join(lines))
