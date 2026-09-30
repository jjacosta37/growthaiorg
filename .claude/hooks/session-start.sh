#!/bin/bash
# SessionStart hook for Claude Code on the web: installs backend and frontend
# dependencies and starts Postgres + Redis so pytest, ruff, vitest and the dev
# servers all work in the sandbox. Idempotent; a no-op outside remote sessions.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# --- Backend: Python 3.13 venv (matches backend/Dockerfile) ---
if [ ! -x .venv/bin/python ]; then
  python3.13 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r backend/requirements-dev.txt

# --- Postgres: the luka role/db the settings expect (dev compose uses host port 5433) ---
PG_CONF=$(ls /etc/postgresql/*/main/postgresql.conf | head -1)
if ! grep -q "^port = 5433" "$PG_CONF"; then
  sed -i "s/^port = .*/port = 5433/" "$PG_CONF"
fi
service postgresql start >/dev/null
for _ in $(seq 1 30); do
  pg_isready -h localhost -p 5433 -q && break
  sleep 1
done
su postgres -c "psql -p 5433 -tAc \"SELECT 1 FROM pg_roles WHERE rolname='luka'\"" | grep -q 1 \
  || su postgres -c "psql -p 5433 -c \"CREATE ROLE luka SUPERUSER LOGIN PASSWORD 'luka'\""
su postgres -c "psql -p 5433 -tAc \"SELECT 1 FROM pg_database WHERE datname='luka'\"" | grep -q 1 \
  || su postgres -c "createdb -p 5433 -O luka luka"

# --- Redis: Celery broker for the worker/beat and eager-free runs ---
redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes >/dev/null

# --- Local dev database: schema + admin user (admin/admin unless .env says otherwise) ---
(
  cd backend
  export DJANGO_SETTINGS_MODULE=config.settings.dev
  export LUKA_ADMIN_USERNAME="${LUKA_ADMIN_USERNAME:-admin}"
  export LUKA_ADMIN_PASSWORD="${LUKA_ADMIN_PASSWORD:-admin}"
  ../.venv/bin/python manage.py migrate --noinput >/dev/null
  ../.venv/bin/python manage.py bootstrap >/dev/null
)

# --- Frontend ---
(cd frontend && npm install --no-audit --no-fund --silent)

# --- Session environment ---
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\""
    echo "export VIRTUAL_ENV=\"$CLAUDE_PROJECT_DIR/.venv\""
    echo "export DATABASE_URL=postgres://luka:luka@localhost:5433/luka"
    echo "export REDIS_URL=redis://localhost:6379/0"
    echo "export REDDIT_SOURCE=\${REDDIT_SOURCE:-fake}"
  } >> "$CLAUDE_ENV_FILE"
fi
