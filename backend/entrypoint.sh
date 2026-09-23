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

# Trust X-Forwarded-* from the reverse proxy so request.client.host is the
# real client IP (per-client rate limiting) instead of the proxy's address
# (issue #173).
#
# Only proxies on a private network are trusted: nginx and Traefik reach the
# backend over a Docker bridge (172.16.0.0/12, or 192.168.0.0/16 once Docker
# runs out of 172.x) or a Swarm overlay (10.0.0.0/8). "*" would also let
# uvicorn take the *leftmost* X-Forwarded-For entry, which the client writes
# itself; with a list, uvicorn walks the header from the right and stops at
# the first address that isn't a trusted proxy, i.e. the one nginx/Traefik
# actually saw. If your proxy reaches the backend from a public address, set
# FORWARDED_ALLOW_IPS to its address (comma-separated IPs or CIDRs).
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7}"

# Serve over HTTPS when certs are mounted (local mkcert setup); otherwise
# plain HTTP behind whatever TLS-terminating proxy is in front.
if [ -f /app/certs/localhost+2.pem ] && [ -f /app/certs/localhost+2-key.pem ]; then
    echo "Starting uvicorn with TLS..."
    exec uvicorn app.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --proxy-headers \
        --forwarded-allow-ips "$FORWARDED_ALLOW_IPS" \
        --ssl-keyfile=/app/certs/localhost+2-key.pem \
        --ssl-certfile=/app/certs/localhost+2.pem
fi

echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    --proxy-headers --forwarded-allow-ips "$FORWARDED_ALLOW_IPS"
