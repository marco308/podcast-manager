# Deployment Guide

This guide covers deploying Podcast Manager to a Docker Swarm cluster.

## Prerequisites

- Docker Swarm initialized (`docker swarm init`)
- The `portpilot_default` network exists (external network for reverse proxy)
- Environment variables configured in `.env` file

## Quick Deploy

From the project root directory:

```bash
# 1. Build the images
docker build -t podcast-manager-backend:latest ./backend
docker build -t podcast-manager-frontend:latest ./frontend

# 2. Update the swarm services
docker service update --force podcast-manager_backend
docker service update --force podcast-manager_frontend
```

## Full Deployment Steps

### 1. Build Docker Images

Build both backend and frontend images:

```bash
# Backend (FastAPI)
docker build -t podcast-manager-backend:latest ./backend

# Frontend (React + Nginx)
docker build -t podcast-manager-frontend:latest ./frontend
```

To force a full rebuild (ignoring cache):

```bash
docker build --no-cache -t podcast-manager-backend:latest ./backend
docker build --no-cache -t podcast-manager-frontend:latest ./frontend
```

### 2. Deploy to Swarm

**First-time deployment:**

```bash
docker stack deploy -c docker-compose.yml podcast-manager
```

**Update existing deployment:**

```bash
# Update both services with new images
docker service update --force podcast-manager_backend
docker service update --force podcast-manager_frontend
```

### 3. Verify Deployment

Check service status:

```bash
# View all services
docker service ls | grep podcast-manager

# Check service tasks
docker service ps podcast-manager_backend
docker service ps podcast-manager_frontend
```

View logs:

```bash
# Backend logs
docker service logs podcast-manager_backend -f

# Frontend logs
docker service logs podcast-manager_frontend -f
```

## Service Architecture

| Service | Image | Port | URL |
|---------|-------|------|-----|
| Backend | podcast-manager-backend:latest | 8000 | api-podcastmanager.marcuslab.uk |
| Frontend | podcast-manager-frontend:latest | 80 | podcastmanager.marcuslab.uk |

## Troubleshooting

### Check service health

```bash
# View running tasks
docker service ps podcast-manager_backend --no-trunc

# Check container logs for errors
docker service logs podcast-manager_backend --tail 50
```

### Force restart a service

```bash
docker service update --force podcast-manager_backend
```

### Scale services

```bash
docker service scale podcast-manager_backend=2
docker service scale podcast-manager_frontend=2
```

### Remove and redeploy

```bash
# Remove the stack
docker stack rm podcast-manager

# Wait for cleanup
sleep 10

# Redeploy
docker stack deploy -c docker-compose.yml podcast-manager
```

### Login loop after deployment

Sessions are stored in-memory on the backend. When the backend container restarts, all sessions are invalidated. Users will need to log in again after deployment.

### 404 errors for assets after frontend update

If you see 404 errors for JS/CSS assets after deploying:

1. **Check for duplicate stacks** - Ensure only one stack is running:
   ```bash
   docker service ls | grep podcast
   ```
   If you see both `podcast_frontend` and `podcast-manager_frontend`, remove the old one:
   ```bash
   docker stack rm podcast
   ```

2. **Hard refresh the browser** - Press Ctrl+Shift+R (or Cmd+Shift+R on Mac) to bypass browser cache.

3. **Verify the container has correct files**:
   ```bash
   docker exec $(docker ps -q -f name=podcast-manager_frontend) ls /usr/share/nginx/html/assets/
   ```

## Data Persistence

The SQLite database is stored in `./data/podcast_manager.db` and mounted as a volume. This data persists across deployments.

## Environment Variables

Required environment variables (in `.env`):

- `SPOTIFY_CLIENT_ID` - Spotify API client ID
- `SPOTIFY_CLIENT_SECRET` - Spotify API client secret
- `SPOTIFY_REDIRECT_URI` - OAuth callback URL
- `ENCRYPTION_KEY` - Fernet encryption key for token storage
- `SECRET_KEY` - Application secret key
