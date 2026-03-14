#!/bin/bash
set -e

# Deployment script for Podcast Manager
# Usage: ./deploy.sh [backend|frontend|all]

COMPONENT="${1:-all}"

echo "Deploying: $COMPONENT"

case "$COMPONENT" in
    backend)
        echo "Building backend..."
        docker build -t podcast-manager-backend:latest ./backend
        echo "Updating backend service..."
        docker service update --force podcast-manager_backend
        echo "Waiting for service to start..."
        sleep 10
        echo "Running database migrations..."
        docker exec $(docker ps -q -f name=podcast-manager_backend) alembic upgrade head
        ;;
    frontend)
        echo "Building frontend..."
        docker build -t podcast-manager-frontend:latest ./frontend
        echo "Updating frontend service..."
        docker service update --force podcast-manager_frontend
        ;;
    all)
        echo "Building backend..."
        docker build -t podcast-manager-backend:latest ./backend
        echo "Building frontend..."
        docker build -t podcast-manager-frontend:latest ./frontend
        echo "Updating services..."
        docker service update --force podcast-manager_backend
        docker service update --force podcast-manager_frontend
        echo "Running database migrations..."
        sleep 5
        docker exec $(docker ps -q -f name=podcast-manager_backend) alembic upgrade head
        ;;
    *)
        echo "Usage: $0 [backend|frontend|all]"
        exit 1
        ;;
esac

echo ""
echo "Waiting for services to stabilize..."
sleep 5

echo ""
echo "Service status:"
docker service ls | grep podcast-manager

echo ""
echo "Deployment complete!"
