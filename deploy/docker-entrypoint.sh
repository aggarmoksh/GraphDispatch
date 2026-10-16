#!/bin/sh
# Seed the graph (idempotent), then serve with exactly one worker (the per-IP limiter is in memory).
set -eu

echo "waiting for FalkorDB at ${FALKORDB_HOST:-localhost}:${FALKORDB_PORT:-6379}"
python - <<'PY'
import os, socket, sys, time
host, port = os.getenv("FALKORDB_HOST", "localhost"), int(os.getenv("FALKORDB_PORT", "6379"))
for _ in range(60):
    try:
        socket.create_connection((host, port), timeout=2).close()
        sys.exit(0)
    except OSError:
        time.sleep(1)
sys.exit("FalkorDB did not become reachable")
PY

echo "loading seed into graph ${GRAPH_NAME:-sjfd}"
python scripts/load.py

exec python -m uvicorn graphdispatch.api:app --host 0.0.0.0 --port 8000 --workers 1
