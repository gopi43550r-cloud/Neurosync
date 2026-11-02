#!/usr/bin/env bash
#
# Back up the NeuroSync production database and uploads to a timestamped folder.
#
#   ./scripts/backup.sh [output-dir]      # default output dir: ./backups
#
# Assumes docker-compose.prod.yml lives in the repo root and its stack is up.
# The database is copied with the SQLite online-backup API, so the snapshot is
# consistent even while the app is running. Uploads and the database live on the
# same volume, so one snapshot captures all state.
#
# Override COMPOSE_FILE / SERVICE to target a different compose project.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SERVICE="${SERVICE:-backend}"
OUT_DIR="${1:-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT_DIR/$STAMP"

mkdir -p "$DEST"

echo "==> Backing up database (consistent snapshot)..."
docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" python -c \
  "import sqlite3,sys; s=sqlite3.connect('/app/data/neurosync.db'); d=sqlite3.connect('/tmp/neurosync-backup.db'); s.backup(d); d.close(); s.close(); sys.stdout.buffer.write(open('/tmp/neurosync-backup.db','rb').read())" \
  > "$DEST/neurosync.db"

echo "==> Backing up uploads..."
docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
  tar -C /app/data -cf - uploads > "$DEST/uploads.tar"

echo "==> Backup complete: $DEST"
ls -lh "$DEST"
