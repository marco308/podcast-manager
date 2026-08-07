#!/bin/sh
# Container healthcheck: probe /api/health over whichever scheme uvicorn is
# actually serving. entrypoint.sh switches to TLS when the mkcert certs are
# mounted, so mirror the same file check here — an http:// probe against a
# TLS listener fails and puts the container in an unhealthy-kill loop
# (issue #177). -k because the mkcert CA isn't in the container's trust store.
# 127.0.0.1 rather than localhost: uvicorn binds IPv4 only, so localhost costs
# a failed ::1 attempt on every probe.
set -eu

if [ -f /app/certs/localhost+2.pem ] && [ -f /app/certs/localhost+2-key.pem ]; then
    exec curl -fsk https://127.0.0.1:8000/api/health
fi

exec curl -fs http://127.0.0.1:8000/api/health
