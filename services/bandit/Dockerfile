# RAVEL — Bandit (Actor + Learner) image (multi-stage)
# Same pattern as services/orchestrator/Dockerfile.

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# build-essential + libffi-dev for asyncpg/cryptography wheels;
# numpy/scipy/boto3 ship pre-built wheels for ARM64.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH

RUN groupadd -r ravel && useradd -r -g ravel -u 1000 ravel

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app/ /app/app/

RUN chown -R ravel:ravel /app
USER ravel

EXPOSE 8002

CMD ["python", "-m", "app.main"]
