#!/bin/bash
set -euo pipefail

# Deployment script for Podcast Manager
# Usage: [REGISTRY=registry.example.com/you] ./deploy.sh [backend|frontend|all]
#
# Without REGISTRY the images are built locally as :latest and the services
# are bounced with --force — which only works on a single-node swarm, since
# other nodes would keep running whatever stale image they already have
# (issue #169). For a multi-node swarm, set REGISTRY to a prefix every node
# can pull from; the script then tags/pushes both images and repoints the
# services at the pushed reference (resolved to a digest on update).

COMPONENT="${1:-all}"
BACKEND_SERVICE="podcast-manager_backend"
FRONTEND_SERVICE="podcast-manager_frontend"
REGISTRY="${REGISTRY:-}"

case "$COMPONENT" in
    backend|frontend|all) ;;
    *)
        echo "Usage: [REGISTRY=...] $0 [backend|frontend|all]"
        exit 1
        ;;
esac

# A locally-built image only exists on this node; refuse a registry-less
# deploy on a multi-node swarm rather than silently deploying stale images.
if [[ -z "$REGISTRY" ]]; then
    # `docker node ls` only answers on a swarm manager. Anywhere else it exits
    # non-zero, which under `set -e -o pipefail` would abort the assignment and
    # kill the script with no message — so absorb the failure and treat it as
    # "no multi-node hazard to check"; the service update below fails loudly on
    # its own if this host really can't talk to the swarm.
    NODE_COUNT=$(docker node ls --quiet 2>/dev/null | wc -l | tr -d ' ') || NODE_COUNT=0
    if (( NODE_COUNT > 1 )); then
        echo "ERROR: this swarm has ${NODE_COUNT} nodes but REGISTRY is not set." >&2
        echo "A locally-built :latest only exists on this node, so tasks scheduled" >&2
        echo "elsewhere would run (and roll back to) a stale image. Set REGISTRY to" >&2
        echo "a registry every node can reach, e.g.:" >&2
        echo "    REGISTRY=registry.example.com/you $0 $COMPONENT" >&2
        exit 1
    fi
fi

echo "Deploying: $COMPONENT"

# Wait until at least one replica of the named swarm service reports Running.
# Polls `docker service ps` rather than racing a fixed sleep against the
# service update, and never passes multiple container IDs into `docker exec`
# (which would silently operate on the first match only).
wait_for_service() {
    local service="$1"
    local timeout=120
    local elapsed=0
    echo "Waiting for $service to report Running (timeout: ${timeout}s)..."
    while (( elapsed < timeout )); do
        if docker service ps --filter desired-state=running \
            --format '{{.CurrentState}}' "$service" 2>/dev/null | grep -q '^Running'; then
            echo "$service is running."
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    echo "ERROR: $service did not reach Running state within ${timeout}s" >&2
    docker service ps "$service" >&2 || true
    return 1
}

# Build one component's image; with REGISTRY, also tag and push it so every
# swarm node can pull the exact build being deployed.
build_image() {
    local component="$1"
    local image="podcast-manager-${component}:latest"
    echo "Building ${component}..."
    docker build -t "$image" "./${component}"
    if [[ -n "$REGISTRY" ]]; then
        echo "Pushing ${REGISTRY}/${image}..."
        docker tag "$image" "${REGISTRY}/${image}"
        docker push "${REGISTRY}/${image}"
    fi
}

# Update the swarm service. With REGISTRY the service is repointed at the
# pushed reference — Swarm resolves it to a digest, so every node pulls this
# exact build (and rollback targets the previous digest). Without it, --force
# restarts the service on the locally-built :latest.
update_service() {
    local component="$1"
    local service="$2"
    echo "Updating ${service}..."
    if [[ -n "$REGISTRY" ]]; then
        docker service update --force --with-registry-auth \
            --image "${REGISTRY}/podcast-manager-${component}:latest" "$service"
    else
        docker service update --force "$service"
    fi
}

# Migrations run in the container's entrypoint (backend/entrypoint.sh) before
# uvicorn starts, so a task that reaches Running has already migrated — and
# the compose path gets the same treatment (issue #149). A failing migration
# exits the container, which surfaces here as wait_for_service timing out.

case "$COMPONENT" in
    backend)
        build_image backend
        update_service backend "$BACKEND_SERVICE"
        wait_for_service "$BACKEND_SERVICE"
        ;;
    frontend)
        build_image frontend
        update_service frontend "$FRONTEND_SERVICE"
        wait_for_service "$FRONTEND_SERVICE"
        ;;
    all)
        build_image backend
        build_image frontend
        update_service backend "$BACKEND_SERVICE"
        update_service frontend "$FRONTEND_SERVICE"
        wait_for_service "$BACKEND_SERVICE"
        wait_for_service "$FRONTEND_SERVICE"
        ;;
esac

echo ""
echo "Service status:"
docker service ls | grep podcast-manager || true

echo ""
echo "Deployment complete!"
