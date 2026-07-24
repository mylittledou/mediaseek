# ==============================================================================
# MediaSeek M3U8 Downloader Dockerfile
# ==============================================================================
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

LABEL org.opencontainers.image.source="https://github.com/mylittledou/mediaseek"
LABEL org.opencontainers.image.description="High performance M3U8 Web Downloader with real-time progress tracking"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY backend /app/backend
COPY frontend /app/frontend

# Create default download directory
ENV DOWNLOAD_DIR=/downloads
RUN mkdir -p /downloads

EXPOSE 8000

WORKDIR /app/backend

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
