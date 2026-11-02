#!/usr/bin/env bash
#
# Restore the NeuroSync database and uploads from a backup produced by
# scripts/backup.sh.
#
#   ./scripts/restore.sh backups/20260101T000000Z
#
# WARNING: this OVERWRITES the current database and uploads. You must confirm.
# The backend is stopped first so nothing writes to the volume mid-restore.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
SERVICE="${SERVICE:-backend}"
SRC="${1:?usage: restore.sh <backup-dir>}"

if [ ! -f "$SRC/neurosync.db" ] || [ ! -f "$SRC/uploads.tar" ]; then
  echo "error: $SRC must contain both neurosync.db and uploads.tar" >&2
  exit 1
fi

read -r -p "This will OVERWRITE the current database and uploads. Type 'yes' to continue: " reply
[ "$reply" = "yes" ] || { echo "aborted"; exit 1; }

echo "==> Stopping backend to prevent writes..."
docker compose -f "$COMPOSE_FILE" stop backend

echo "==> Restoring database..."
docker compose -f "$COMPOSE_FILE" run --rm -T --no-deps "$SERVICE" \
  sh -c 'cat > /app/data/neurosync.db && rm -f /app/data/neurosync.db-wal /app/data/neurosync.db-shm' \
  < "$SRC/neurosync.db"

echo "==> Restoring uploads..."
docker compose -f "$COMPOSE_FILE" run --rm -T --no-deps "$SERVICE" \
  sh -c 'rm -rf /app/data/uploads && mkdir -p /app/data/uploads && tar -C /app/data -xf -' \
  < "$SRC/uploads.tar"

echo "==> Starting backend..."
docker compose -f "$COMPOSE_FILE" start backend

echo "==> Restore complete. Check the logs with:"
echo "    docker compose -f $COMPOSE_FILE logs -f backend"
