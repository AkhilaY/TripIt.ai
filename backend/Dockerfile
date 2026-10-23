FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg rclone ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Backups (start.sh): Litestream streams the database to Cloudflare R2; rclone copies photos and keys.
ARG LITESTREAM_VERSION=0.3.13
RUN arch="$(dpkg --print-architecture)" \
    && curl -fsSL -o /tmp/litestream.deb \
       "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-${arch}.deb" \
    && dpkg -i /tmp/litestream.deb && rm /tmp/litestream.deb

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
COPY litestream.yml start.sh ./

ENV PORT=8080
ENV DATABASE_PATH=/data/tripit.db
VOLUME /data
EXPOSE 8080
CMD ["/app/start.sh"]
