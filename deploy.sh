#!/bin/bash
set -euo pipefail

# Deployment script for Podcast Manager
# Usage: ./deploy.sh [backend|frontend|all]
#
# Images are built locally on whichever node you run this from. Swarm does NOT
# distribute locally-built images between nodes, so a service pinned to a
# *different* node than the build host would otherwise keep running whatever
# stale image that node happens to have — silently, with the update reporting
# success. That is exactly what happened after the frontend moved to zaphod:
# `docker service update --force` restarted it against a 5-week-old image for
# over a month.
#
# This script therefore resolves each service's target node from its placement
# constraint and ships the freshly-built image there before updating. Nothing
# is hardcoded to a particular node — move a service and the transfer follows.
#
# If you ever add a registry, replace ship_image_to_node() with a push/pull and
# everything else stays as-is.

COMPONENT="${1:-all}"

# Build contexts below are relative, so operate on the repo this script lives
# in rather than whatever directory it happened to be invoked from.
cd "$(dirname "${BASH_SOURCE[0]}")"

STACK="podcast-manager"
BACKEND_SERVICE="${STACK}_backend"
FRONTEND_SERVICE="${STACK}_frontend"
BACKEND_IMAGE="podcast-manager-backend:latest"
FRONTEND_IMAGE="podcast-manager-frontend:latest"

case "$COMPONENT" in
    backend|frontend|all) ;;
    *)
        echo "Usage: $0 [backend|frontend|all]"
        exit 1
        ;;
esac

echo "Deploying: $COMPONENT"

# The Docker daemon's own name, which matches the Swarm node hostname used in
# `node.hostname == ...` placement constraints.
this_node() {
    docker info --format '{{.Name}}'
}

# Hostname this service is pinned to via a `node.hostname == <name>` placement
# constraint, or empty if it is unconstrained (i.e. could run anywhere, which
# for locally-built images means it must be able to run here).
service_target_node() {
    local service="$1"
    docker service inspect "$service" \
        --format '{{range .Spec.TaskTemplate.Placement.Constraints}}{{println .}}{{end}}' 2>/dev/null \
        | sed -n 's/^[[:space:]]*node\.hostname[[:space:]]*==[[:space:]]*//p' \
        | head -n1 \
        | tr -d '[:space:]'
}

# Content digests of an image's filesystem layers.
#
# Deliberately NOT the image ID: `docker save`/`docker load` does not preserve
# it (BuildKit attestation metadata is dropped in the round-trip), so the same
# image legitimately has different IDs on the two nodes. The RootFS layer
# digests are content-addressed and do survive, which makes them the right
# thing to compare.
LAYER_FMT='{{range .RootFS.Layers}}{{println .}}{{end}}'

image_layers_here() {
    docker image inspect "$1" --format "$LAYER_FMT" 2>/dev/null || true
}

image_layers_on() {
    ssh -o BatchMode=yes "$2" "docker image inspect '$1' --format '$LAYER_FMT'" 2>/dev/null || true
}

# Copy a locally-built image to another Swarm node over SSH. Gzipped because
# `docker save` emits uncompressed layer tarballs and this usually crosses a
# real network.
ship_image_to_node() {
    local image="$1" node="$2"

    echo "Shipping $image to $node (no registry in this setup)..."
    if ! docker save "$image" | gzip | ssh -o BatchMode=yes "$node" 'gunzip | docker load'; then
        echo "ERROR: failed to ship $image to $node." >&2
        echo "  Check that 'ssh $node' works non-interactively from $(this_node)." >&2
        return 1
    fi

    # Confirm the target actually has the content we just built, rather than
    # trusting that `docker load` said something reassuring.
    local here there
    here=$(image_layers_here "$image")
    there=$(image_layers_on "$image" "$node")

    if [[ -z "$there" ]]; then
        echo "ERROR: $image is not present on $node after loading it." >&2
        return 1
    fi
    if [[ "$here" != "$there" ]]; then
        echo "ERROR: $node has a different build of $image than the one just built." >&2
        echo "  local layers:  $(tr -d '\n' <<<"$here" | md5sum | cut -c1-12)" >&2
        echo "  remote layers: $(tr -d '\n' <<<"$there" | md5sum | cut -c1-12)" >&2
        return 1
    fi
    echo "$node now has $image ($(grep -c . <<<"$here") layers, content verified)."
}

# Make an image available wherever its service is scheduled to run.
publish_image() {
    local image="$1" service="$2"
    local target
    target=$(service_target_node "$service")

    if [[ -z "$target" ]]; then
        echo "NOTE: $service has no node.hostname constraint — assuming it runs on $(this_node)."
        echo "      If Swarm schedules it elsewhere it will not find the local image."
        return 0
    fi

    if [[ "$target" == "$(this_node)" ]]; then
        echo "$service runs on $target (this node) — image already available."
        return 0
    fi

    ship_image_to_node "$image" "$target"
}

# Wait until the named service reports a completed rolling update and has a
# task in Running state.
wait_for_service() {
    local service="$1"
    local timeout=120
    local elapsed=0
    echo "Waiting for $service to converge (timeout: ${timeout}s)..."
    while (( elapsed < timeout )); do
        local update_state
        update_state=$(docker service inspect "$service" --format '{{if .UpdateStatus}}{{.UpdateStatus.State}}{{end}}' 2>/dev/null || true)

        case "$update_state" in
            paused|rollback_started|rollback_completed)
                echo "ERROR: $service update did not succeed (state: $update_state)" >&2
                docker service ps "$service" --no-trunc >&2 || true
                return 1
                ;;
        esac

        if docker service ps --filter desired-state=running \
            --format '{{.CurrentState}}' "$service" 2>/dev/null | grep -q '^Running'; then
            echo "$service is running."
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    echo "ERROR: $service did not reach Running state within ${timeout}s" >&2
    docker service ps "$service" --no-trunc >&2 || true
    return 1
}

# Build -> ship to the right node -> roll the service.
#
# Backend migrations run in the container entrypoint (backend/entrypoint.sh)
# before uvicorn starts, so a task that reaches Running has already migrated
# (issue #149). A failing migration exits the container, which surfaces here
# as the update failing or wait_for_service timing out.
deploy_component() {
    local name="$1" service="$2" image="$3" context="$4"

    echo ""
    echo "=== $name ==="
    echo "Building $image..."
    docker build -t "$image" "$context"

    publish_image "$image" "$service"

    echo "Updating $service..."
    docker service update --force "$service" >/dev/null
    wait_for_service "$service"
}

case "$COMPONENT" in
    backend)
        deploy_component "backend" "$BACKEND_SERVICE" "$BACKEND_IMAGE" ./backend
        ;;
    frontend)
        deploy_component "frontend" "$FRONTEND_SERVICE" "$FRONTEND_IMAGE" ./frontend
        ;;
    all)
        # Backend first: the frontend proxies /api to it, and the backend also
        # carries the migrations.
        deploy_component "backend" "$BACKEND_SERVICE" "$BACKEND_IMAGE" ./backend
        deploy_component "frontend" "$FRONTEND_SERVICE" "$FRONTEND_IMAGE" ./frontend
        ;;
esac

echo ""
echo "Service status:"
docker service ls | grep "$STACK" || true

echo ""
echo "Deployment complete!"
