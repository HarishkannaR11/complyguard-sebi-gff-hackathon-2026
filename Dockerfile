#
# RegOps AI API image. Build from the repo root:
#   docker build -t regops-api .
#
# Run exactly ONE replica: the audit hash chain's lock is per process and upload jobs run
# in-process, so a second API process can fork the chain. Do not add uvicorn --workers.

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf

# libgomp: OpenMP runtime used by torch's CPU kernels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch first (the default wheel drags in ~2 GB of CUDA libraries we cannot use on
# Fargate/t3), then the rest. Kept in its own layer so code changes don't reinstall it.
COPY requirements.txt .
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

# Bake the embedding model into the image so containers start fast and never need to reach
# huggingface.co at runtime. Build with --build-arg PRELOAD_MODEL=0 to skip (then the model
# is downloaded on first use and the container needs internet access).
ARG PRELOAD_MODEL=1
ARG EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
RUN if [ "$PRELOAD_MODEL" = "1" ]; then \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"; \
    fi
# Deployments set HF_HUB_OFFLINE=1 (see deploy/) so the app never calls huggingface.co at runtime.

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
COPY evals ./evals

# Non-root. /app/data holds uploaded PDFs; /app/qdrant_db is the embedded-Qdrant fallback path.
RUN useradd --uid 10001 --home-dir /app --no-create-home --shell /usr/sbin/nologin regops \
    && mkdir -p /app/data/raw_pdfs /app/qdrant_db "$HF_HOME" \
    && chown -R regops:regops /app "$HF_HOME"
USER regops

EXPOSE 8000

# /livez is the shallow check (no DB/Qdrant), so a dependency blip can't get the container killed.
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=4 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/livez', timeout=4).status == 200 else 1)"

# Migrations and the LangGraph checkpointer are set up by the app's lifespan hook at startup.
# --proxy-headers: trust X-Forwarded-* from the reverse proxy / ALB in front of us.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
