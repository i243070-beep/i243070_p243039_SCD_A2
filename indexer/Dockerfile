# RAHBAR indexer image: the Job that writes the index (section 4.2). Build context: indexer/
FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# OCR needs system packages, not only pip packages (see requirements.txt):
#   tesseract-ocr + English data -> pytesseract; poppler-utils -> pdf2image (pdftoppm).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pipeline ./pipeline

# The corpus is baked into the image (decision recorded in docs/PIPELINE.md): `make images`
# copies the fetched documents and _index.json into indexer/corpus/ before the build. The
# PDFs are never committed (corpus/raw/ is gitignored). In CI a ConfigMap is mounted over
# /corpus instead, so the same image indexes the small fixture corpus.
COPY corpus/ /corpus/

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin rahbar
USER 10001:10001

# A Job: it runs once and exits. Exit code 0 means the index was written.
# Kubernetes `args` REPLACES the CMD, so the manifests also spell out `command`.
CMD ["python", "-m", "pipeline.run"]
