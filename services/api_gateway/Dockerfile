# RAVEL — API Gateway image (multi-stage)
# Stage 1: build a venv with all dependencies.
# Stage 2: minimal runtime, copies the venv, runs as non-root user.

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build deps for cryptography / bcrypt wheels (slim image lacks them).
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

# Non-root user for least-privilege execution.
RUN groupadd -r ravel && useradd -r -g ravel -u 1000 ravel

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app/ /app/app/

RUN chown -R ravel:ravel /app
USER ravel

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
