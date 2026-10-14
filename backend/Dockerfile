FROM python:3.14-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Which commit this image is, reported by /api/health. CI passes the SHA, and a
# local build leaves "unknown". Set late so it doesn't bust the layer cache.
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

# Create data directory for SQLite
RUN mkdir -p /app/data

# Ensure the entrypoint and healthcheck are executable regardless of the
# host's file mode
RUN chmod +x /app/entrypoint.sh /app/healthcheck.sh

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Health check — healthcheck.sh probes https when certs are mounted, http
# otherwise, matching what entrypoint.sh serves (issue #177)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD /app/healthcheck.sh || exit 1

# Apply migrations, then serve (HTTPS if certs are mounted)
CMD ["/app/entrypoint.sh"]
