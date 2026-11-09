# RAHBAR api image. Build context: api/   (see Makefile `make images`)
# Pinned base tag: an unpinned image is the drift problem from Lecture 04.
FROM python:3.12.11-slim-bookworm

# No .pyc files (the root filesystem is read-only on the cluster) and unbuffered logs to stdout (section 4.8).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Pull the security fixes for the OS packages of the base image (Trivy fails the build on fixable HIGH/CRITICAL findings).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Non-root user (section 4.7). A numeric UID lets Kubernetes verify runAsNonRoot.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin rahbar
USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
