# Build stage. Both base images are pinned by digest as well as tag, so a
# rebuild can't pick up a re-pushed tag unannounced; Dependabot's docker
# ecosystem bumps tag and digest together.
FROM node:26-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Production stage. A versioned tag (1.31 = current mainline, which is what
# the bare `alpine` tag tracks) rather than `nginx:alpine`, so Dependabot can
# see and propose the next version instead of it changing silently on rebuild.
FROM nginx:1.31-alpine@sha256:fed7e14be83cbd2661a75cdc5b872d936cf155d46c327084d30b8df19ae88d72

# Copy built assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Create non-root user and make every path nginx writes at runtime owned by
# it: temp/cache dirs, logs, and the pid file. nginx listens on the
# unprivileged port 8080 (see nginx.conf) so no root is needed to bind.
RUN adduser -D -g '' appuser \
    && chown -R appuser:appuser /usr/share/nginx/html \
    && chown -R appuser:appuser /var/cache/nginx \
    && chown -R appuser:appuser /var/log/nginx \
    && touch /var/run/nginx.pid \
    && chown appuser:appuser /var/run/nginx.pid

USER appuser

EXPOSE 8080

# Health check. 127.0.0.1, not localhost: nginx binds IPv4 only, and busybox
# wget resolves localhost to ::1 first and gives up there ("connection
# refused") instead of falling back — matching the Traefik stack's probe.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:8080/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
