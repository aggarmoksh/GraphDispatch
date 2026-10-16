# GraphDispatch app image. Runtime only: no tests, no data/, no .env, no screenshots.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 app
WORKDIR /app

# Pinned runtime dependencies first (cached layer). requirements-runtime.txt is generated from requirements.txt.
COPY requirements-runtime.txt ./
RUN pip install -r requirements-runtime.txt

# Only what runtime needs: the package (with its static page), the seed data, the idempotent loader.
COPY pyproject.toml ./
COPY graphdispatch ./graphdispatch
COPY seed ./seed
COPY scripts/load.py ./scripts/load.py
COPY deploy/docker-entrypoint.sh ./docker-entrypoint.sh
RUN pip install --no-deps -e . \
    && mkdir -p /app/runs \
    && chmod +x /app/docker-entrypoint.sh \
    && chown -R app:app /app

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["/app/docker-entrypoint.sh"]
