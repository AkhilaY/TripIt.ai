#!/bin/sh
# Starts the server. With backups set up (BACKUP_* settings), it:
#   - restores the database and files from the bucket when the disk is empty (a new or lost volume),
#   - streams every database change to the bucket with Litestream (within about 10 seconds),
#   - copies photos and keys to the bucket every 15 minutes and once more when the machine stops.
set -eu

DB="${DATABASE_PATH:-/data/tripit.db}"
DATA_DIR="$(dirname "$DB")"
APP="uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"
CONFIG="${LITESTREAM_CONFIG:-/app/litestream.yml}"

if [ -z "${BACKUP_BUCKET:-}" ]; then
  echo "Backups are off (set BACKUP_BUCKET and the other BACKUP_* settings to turn them on)"
  exec $APP
fi

export DATABASE_PATH="$DB"
export LITESTREAM_ACCESS_KEY_ID="${BACKUP_ACCESS_KEY_ID:-}"
export LITESTREAM_SECRET_ACCESS_KEY="${BACKUP_SECRET_ACCESS_KEY:-}"
# rclone reads its "backup" remote from these.
export RCLONE_CONFIG_BACKUP_TYPE=s3
export RCLONE_CONFIG_BACKUP_PROVIDER="${BACKUP_PROVIDER:-Cloudflare}"
export RCLONE_CONFIG_BACKUP_ACCESS_KEY_ID="${BACKUP_ACCESS_KEY_ID:-}"
export RCLONE_CONFIG_BACKUP_SECRET_ACCESS_KEY="${BACKUP_SECRET_ACCESS_KEY:-}"
export RCLONE_CONFIG_BACKUP_ENDPOINT="${BACKUP_ENDPOINT:-}"
FILES="backup:${BACKUP_BUCKET}/files"
mkdir -p "$DATA_DIR"

sync_files() {
  # Everything on the volume except the database (Litestream has that, and keeps its working files in the
  # hidden .tripit.db-litestream folder). --max-delete guards against a half-empty disk wiping the backup.
  rclone sync "$DATA_DIR" "$FILES" --exclude "*.db" --exclude "*.db-*" --exclude "*.bak" --exclude ".*" --exclude ".*/**" \
    --max-delete 200 --fast-list --quiet || echo "File backup failed; will retry"
}

if [ ! -f "$DB" ]; then
  echo "No database on the disk: restoring the latest backup, if there is one"
  # A failed restore stops here rather than starting empty and overwriting good backups.
  litestream restore -config "$CONFIG" -if-replica-exists "$DB"
  rclone copy "$FILES" "$DATA_DIR" --ignore-existing --quiet || echo "No files to restore"
fi

# Photos and keys: a minute after starting, then every 15 minutes.
( sleep 60; sync_files; while sleep 900; do sync_files; done ) &
LOOP=$!

# The server runs under Litestream, which streams every change. On stop (Fly sends SIGINT), let it finish
# its last sync and the server shut down, then copy files once more.
litestream replicate -config "$CONFIG" -exec "$APP" &
MAIN=$!
stop() {
  kill -INT "$MAIN" 2>/dev/null || true
  wait "$MAIN" || true
  kill "$LOOP" 2>/dev/null || true
  sync_files
  exit 0
}
trap stop INT TERM
set +e
wait "$MAIN"
STATUS=$?
kill "$LOOP" 2>/dev/null
exit "$STATUS"
