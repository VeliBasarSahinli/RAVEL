# RAVEL — RAG service image (multi-stage)
# Embedding modelini build sırasında image'a indiriyoruz; runtime'da
# download yok, restart sonrası anlık başlangıç.

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Pre-download the embedding model so runtime startup is instant.
# Cache lives at /opt/models inside the venv image; runtime points
# sentence-transformers at this folder via env (config.py).
RUN mkdir -p /opt/models && \
    python -c "from sentence_transformers import SentenceTransformer; \
               SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2', cache_folder='/opt/models')"


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    SENTENCE_TRANSFORMERS_HOME=/opt/models \
    HF_HOME=/opt/models

RUN groupadd -r ravel && useradd -r -g ravel -u 1000 ravel

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/models /opt/models

WORKDIR /app
COPY app/ /app/app/

RUN chown -R ravel:ravel /app /opt/models
USER ravel

EXPOSE 8003

CMD ["python", "-m", "app.main"]
