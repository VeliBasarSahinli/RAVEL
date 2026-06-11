# RAVEL — Manim Worker image (multi-stage)
# Sistem bağımlılıkları (runtime'da):
#   ffmpeg, ghostscript, dvisvgm + minimal TeX Live (texlive-latex-base,
#   texlive-latex-extra, texlive-fonts-recommended, texlive-science).
# Tam TeX Live (~3 GB) ortaokul müfredatı için fazla; bu set
# kesirler/üslü/karekök/geometri için yeterli.
#
# Build süresi: ilk seferinde 10-15 dk (apt + pip wheel); sonraki cache'li.
# Image boyutu beklenen: ~1.6-1.9 GB.

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Manim'in pip kurulumu için system header'ları gerekli (cairo, pango).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev libcairo2-dev libpango1.0-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Build-time smoke test: Manim import edilebiliyor mu?
RUN python -c "from manim import Scene; print('manim ok')"


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH

# Render için runtime bağımlılıkları:
#   ffmpeg     → mp4 encode
#   ghostscript + dvisvgm → LaTeX→SVG (Manim Tex/MathTex)
#   libcairo2 + libpango → Manim Text (cairo/pango runtime)
#   texlive-*  → matematik formüllerinin LaTeX render'ı
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ghostscript dvisvgm \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    texlive-base texlive-latex-base texlive-latex-extra \
    texlive-fonts-recommended texlive-science \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r ravel && useradd -r -g ravel -u 1000 ravel

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app/ /app/app/

# Render geçici dizini — non-root user'ın yazabilmesi gerek.
RUN mkdir -p /tmp/manim_renders && chown -R ravel:ravel /app /tmp/manim_renders
USER ravel

EXPOSE 8004

CMD ["python", "-m", "app.main"]
