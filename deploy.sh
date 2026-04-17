#!/bin/bash
set -euo pipefail

# Deployment script for Podcast Manager
# Usage: ./deploy.sh [backend|frontend|all]

COMPONENT="${1:-all}"
BACKEND_SERVICE="podcast-manager_backend"
FRONTEND_SERVICE="podcast-manager_frontend"

case "$COMPONENT" in
    backend|frontend|all) ;;
    *)
        echo "Usage: $0 [backend|frontend|all]"
        exit 1
        ;;
esac

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

# Run alembic migrations inside the first running backend task. Using the
# task name (service.1.xxx) — not a name-filter on `docker ps` — avoids
# accidentally targeting a sibling stack that happens to match the prefix.
run_migrations() {
    wait_for_service "$BACKEND_SERVICE"
    local task_container
    task_container=$(docker ps \
        --filter "label=com.docker.swarm.service.name=${BACKEND_SERVICE}" \
        --format '{{.ID}}' | head -n1)
    if [[ -z "$task_container" ]]; then
        echo "ERROR: no running container found for $BACKEND_SERVICE" >&2
        return 1
    fi
    echo "Running migrations in container $task_container..."
    docker exec "$task_container" alembic upgrade head
}

case "$COMPONENT" in
    backend)
        echo "Building backend..."
        docker build -t podcast-manager-backend:latest ./backend
        echo "Updating backend service..."
        docker service update --force "$BACKEND_SERVICE"
        run_migrations
        ;;
    frontend)
        echo "Building frontend..."
        docker build -t podcast-manager-frontend:latest ./frontend
        echo "Updating frontend service..."
        docker service update --force "$FRONTEND_SERVICE"
        wait_for_service "$FRONTEND_SERVICE"
        ;;
    all)
        echo "Building backend..."
        docker build -t podcast-manager-backend:latest ./backend
        echo "Building frontend..."
        docker build -t podcast-manager-frontend:latest ./frontend
        echo "Updating services..."
        docker service update --force "$BACKEND_SERVICE"
        docker service update --force "$FRONTEND_SERVICE"
        run_migrations
        wait_for_service "$FRONTEND_SERVICE"
        ;;
esac

echo ""
echo "Service status:"
docker service ls | grep podcast-manager || true

echo ""
echo "Deployment complete!"
