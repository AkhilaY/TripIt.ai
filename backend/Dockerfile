FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# TikTok and Instagram change often; always build with the newest yt-dlp.
RUN pip install --no-cache-dir -U "yt-dlp[default,curl-cffi]"

# A real browser, for opening restaurant websites and clicking through to their menus (app/menu_browser.py).
RUN playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/*

# Pre-download the Whisper model so the first job isn't slow.
ARG WHISPER_MODEL=base
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8')"

COPY app ./app

ENV PORT=8080
ENV DATABASE_PATH=/data/tripit.db
VOLUME /data
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
