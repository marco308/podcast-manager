#!/bin/sh
# Container entrypoint: bring the schema up to date, then start the server.
#
# Alembic is the single source of truth for the schema (issue #149). The app
# used to call Base.metadata.create_all on startup, which left a fresh
# deployment with tables but no alembic_version row — the next
# `alembic upgrade head` would then replay 001_initial against existing
# tables and fail. Running migrations here means both the docker-compose and
# the Swarm paths get a migrated database, every start.
set -eu

# Databases created by the old create_all path have tables but no
# alembic_version row; stamp them so the upgrade below doesn't try to replay
# 001_initial against existing tables. No-op otherwise.
python -m scripts.adopt_legacy_schema

echo "Running database migrations..."
alembic upgrade head

# Serve over HTTPS when certs are mounted (local mkcert setup); otherwise
# plain HTTP behind whatever TLS-terminating proxy is in front.
if [ -f /app/certs/localhost+2.pem ] && [ -f /app/certs/localhost+2-key.pem ]; then
    echo "Starting uvicorn with TLS..."
    exec uvicorn app.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --ssl-keyfile=/app/certs/localhost+2-key.pem \
        --ssl-certfile=/app/certs/localhost+2.pem
fi

echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
