# ==============================================================================
# MediaSeek M3U8 Downloader Dockerfile (Optimized for GHCR & x86_64)
# ==============================================================================
FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/mylittledou/mediaseek"
LABEL org.opencontainers.image.description="High performance M3U8 Web Downloader with real-time progress tracking"
LABEL org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies including sudo & ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    gnupg \
    sudo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright system dependencies & Chromium browser
RUN apt-get update && \
    python -m playwright install-deps chromium && \
    python -m playwright install chromium && \
    rm -rf /var/lib/apt/lists/*

# Copy application files
COPY backend /app/backend
COPY frontend /app/frontend

# Create default download directory
ENV DOWNLOAD_DIR=/downloads
RUN mkdir -p /downloads

EXPOSE 8000

WORKDIR /app/backend

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
