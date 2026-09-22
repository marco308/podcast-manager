#!/bin/bash
set -euo pipefail

# Deployment script for Podcast Manager
# Usage: [REGISTRY=ghcr.io/you] [IMAGE_TAG=<sha>] ./deploy.sh [backend|frontend|all]
#
# With REGISTRY set, this deploys images CI already built and published: no
# build runs here, so the swarm does no compile work, and every node pulls the
# identical image instead of whatever it happened to build locally (issue
# #169). IMAGE_TAG defaults to the checked-out commit, so pull the commit you
# intend to ship before deploying; pass IMAGE_TAG=<sha> to roll back to an
# earlier build, or IMAGE_TAG=latest for the previous moving-tag behaviour.
#
# Without REGISTRY the images are built locally as :latest and the services
# are bounced with --force. That only works on a single-node swarm, since
# other nodes would keep running whatever stale image they already have, so
# the multi-node case is refused below.

COMPONENT="${1:-all}"
BACKEND_SERVICE="podcast-manager_backend"
FRONTEND_SERVICE="podcast-manager_frontend"
REGISTRY="${REGISTRY:-}"

# Deploy the commit that is actually checked out, not a moving :latest. Swarm
# stores the tag rather than resolving it to a digest, so a service left on
# :latest would come back on whatever had been published most recently if a
# task restarted later (node reboot, crash) — not the build it was deployed
# with. Pinning to the commit SHA makes a deploy reproducible and lets a
# rollback name an exact prior build. CI publishes both tags for every merge.
if [[ -n "$REGISTRY" ]]; then
    IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse HEAD 2>/dev/null || echo latest)}"
else
    IMAGE_TAG="${IMAGE_TAG:-latest}"
fi

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

# Build one component's image locally. Only reached in the registry-less
# single-node case: with REGISTRY the image was already built and published
# by CI, and rebuilding it here would put back the compute load on the swarm
# that publishing exists to remove.
build_image() {
    local component="$1"
    echo "Building ${component}..."
    docker build -t "podcast-manager-${component}:latest" "./${component}"
}

# Update the swarm service. With REGISTRY the service is repointed at the
# published reference, which Swarm resolves to a digest so every node pulls
# this exact build; --with-registry-auth forwards the manager's credentials
# so workers can pull a private package. Without it, --force restarts the
# service on the locally-built :latest.
update_service() {
    local component="$1"
    local service="$2"
    echo "Updating ${service}..."
    if [[ -n "$REGISTRY" ]]; then
        docker service update --force --with-registry-auth \
            --image "${REGISTRY}/podcast-manager-${component}:${IMAGE_TAG}" "$service"
    else
        docker service update --force "$service"
    fi
}

# Confirm the image exists before touching any service. Deploying "all" runs
# two updates, so an unpublished tag discovered on the second one would leave
# the stack half-updated. Usually this means CI has not finished publishing
# this commit, or the commit was never merged to main.
require_published_image() {
    local component="$1"
    local ref="${REGISTRY}/podcast-manager-${component}:${IMAGE_TAG}"
    if ! docker manifest inspect "$ref" >/dev/null 2>&1; then
        echo "ERROR: ${ref} is not in the registry." >&2
        echo "CI publishes an image for every merge to main — check that its run has" >&2
        echo "finished, or pass an explicit IMAGE_TAG=<published sha|latest>." >&2
        exit 1
    fi
}

# Migrations run in the container's entrypoint (backend/entrypoint.sh) before
# uvicorn starts, so a task that reaches Running has already migrated — and
# the compose path gets the same treatment (issue #149). A failing migration
# exits the container, which surfaces here as wait_for_service timing out.

if [[ -n "$REGISTRY" ]]; then
    echo "Deploying published images from ${REGISTRY} (tag: ${IMAGE_TAG}); no local build."
    case "$COMPONENT" in
        backend)  require_published_image backend ;;
        frontend) require_published_image frontend ;;
        all)      require_published_image backend; require_published_image frontend ;;
    esac
fi

case "$COMPONENT" in
    backend)
        if [[ -z "$REGISTRY" ]]; then build_image backend; fi
        update_service backend "$BACKEND_SERVICE"
        wait_for_service "$BACKEND_SERVICE"
        ;;
    frontend)
        if [[ -z "$REGISTRY" ]]; then build_image frontend; fi
        update_service frontend "$FRONTEND_SERVICE"
        wait_for_service "$FRONTEND_SERVICE"
        ;;
    all)
        if [[ -z "$REGISTRY" ]]; then
            build_image backend
            build_image frontend
        fi
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
