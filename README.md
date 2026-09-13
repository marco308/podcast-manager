# Podcast Manager

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

A self-hosted web app that brings structure and automation to your Spotify podcast listening. It connects to your Spotify account, pulls in your subscribed podcasts, and lets you assign them directly to managed playlists — then keeps those playlists updated automatically.

## The Problem

Spotify's podcast experience is a single chronological feed. If you subscribe to 30+ podcasts across different genres — daily news, long-form storytelling, casual background listening — they all land in the same pile. There's no way to say "give me today's news episodes in one playlist" or "build me a queue of my favourite shows, oldest episodes first."

## What This App Does

Podcast Manager sits on top of Spotify and adds a **playlist management layer**. You create playlists, assign podcasts to them, and the app continuously builds and maintains the corresponding Spotify playlists for you.

### Core Workflow

1. **Sync** your Spotify podcast library into the app
2. **Create playlists** with an episode mode (all unplayed or latest only)
3. **Assign podcasts** directly to one or more playlists
4. **Configure ordering** and set attributes like sequential (oldest-first for story podcasts)
5. **The app handles the rest** — daily rebuilds, played-episode cleanup, token refresh

### Episode Modes

Each playlist has an episode mode that controls how episodes are selected:

| Mode | Behaviour |
|------|-----------|
| **All Unplayed** | Includes all unplayed episodes from each assigned podcast |
| **Latest Only** | Includes only the most recent unplayed episode per assigned podcast |

### Playlist Settings

- **Weekend Only** — Playlist only populates on Fridays, Saturdays, Sundays, and UK public holidays
- **Ordering Mode** — How episodes are arranged (default, podcast order, chronological asc/desc)
- **Podcast Order** — Drag-and-drop ordering of podcasts within a playlist

### Podcast Attributes

- **Sequential** — Story-based podcasts that must be consumed oldest-to-newest (e.g. serialised true crime). Always ordered oldest-first regardless of playlist settings.

Podcasts can belong to multiple playlists simultaneously, with independent ordering per playlist.

### Ordering Modes

Each playlist can be ordered differently:

- **Default** — Oldest-first for "all unplayed", newest-first for "latest only"
- **Podcast Order** — Group by podcast, ordered by your manual ranking
- **Chronological (oldest first)** — All episodes by release date, ascending
- **Chronological (newest first)** — All episodes by release date, descending

Sequential podcasts always maintain oldest-first ordering within their group, regardless of the playlist's ordering mode.

## Automation

Once configured, the app runs four background jobs:

| Job | Schedule | What it does |
|-----|----------|-------------|
| **Playlist update** | Daily (configurable, default 4 AM) | Rebuilds all enabled playlists with current unplayed episodes |
| **Played episode cleanup** | Every 30 minutes | Removes fully-played episodes from all managed playlists |
| **Token refresh** | Every 45 minutes | Refreshes Spotify access tokens before they expire |
| **Session cleanup** | Every hour | Removes expired user sessions |

## Tech Stack

- **Backend:** FastAPI, async SQLAlchemy, SQLite, APScheduler
- **Frontend:** React 19, TypeScript, Vite, Ant Design
- **Auth:** Spotify OAuth2 with encrypted token storage (Fernet)
- **Deployment:** Docker Swarm behind Traefik reverse proxy

## Screenshots

The app has four main screens:

- **Dashboard** — Quick stats (total podcasts, playlist assignment progress, playlist status) and one-click sync/update buttons
- **Podcasts** — Searchable list with card and table views; inline playlist assignment, sequential toggle, unfollow
- **Playlists** — Playlist CRUD with episode mode and ordering config; drag-and-drop podcast reordering; add/remove podcast assignments
- **Settings** — Spotify account info, theme selector (light/dark/system/auto)

## Setup

### Prerequisites

- A Spotify account and a Spotify Developer application (see below)
- Docker (for deployment) or Python 3.11+ and Node.js (for local dev).
  3.11 is the supported floor (what `ruff`'s `target-version` targets) and CI tests it; the Docker image runs 3.14.

### Registering Your Spotify App (required)

Every self-hosted instance needs its **own** Spotify Developer application — there is no shared instance you can point at:

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and create an app.
2. Add redirect URIs: `https://127.0.0.1:8000/api/auth/callback` for local dev, plus `https://<your-api-domain>/api/auth/callback` for a deployment.
3. Copy the Client ID and Client Secret into `backend/.env`.
4. Under **User Management**, add the Spotify accounts (including your own) that may use your instance.

### Spotify Development Mode Constraints (read this first)

- Dev Mode apps are capped at **25 users**, each manually allowlisted in the dashboard. Extended quota is effectively unavailable to hobby apps, so treat this as software for you and your household — not something to open to the public.
- The app is built for Dev Mode's reduced API surface (Spotify removed the batch "Get Several X" endpoints for Dev Mode apps in early 2026; single-item fetches with low concurrency are used instead).
- There are no admin/user roles in the app itself: anyone allowlisted in your Spotify dashboard can sign in to your instance.
- Spotify OAuth rejects plain-HTTP and `localhost` redirect URIs — hence the HTTPS + `127.0.0.1` requirements below.

### Environment Variables

Copy `backend/.env.example` to `backend/.env` and configure:

```bash
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=https://127.0.0.1:8000/api/auth/callback
ENCRYPTION_KEY=...    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FRONTEND_URL=https://127.0.0.1:3000
PLAYLIST_UPDATE_HOUR=4
PLAYLIST_UPDATE_MINUTE=0
```

> Use `127.0.0.1` (not `localhost`) in the redirect URI — Spotify OAuth rejects `localhost`.

### Local Development

```bash
# Backend (requires local HTTPS certs for Spotify OAuth)
cd backend && mkdir -p certs && cd certs
mkcert -install && mkcert localhost 127.0.0.1 ::1
cd ..
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload \
  --ssl-keyfile=./certs/localhost+2-key.pem \
  --ssl-certfile=./certs/localhost+2.pem

# Frontend
cd frontend
npm install
npm run dev
```

### Running Tests

```bash
cd backend
pytest tests
```

### Production Deployment

**Single host (Docker Compose):**

```bash
cp backend/.env.example backend/.env   # then fill in your values
docker compose up -d --build
```

The app is served on port 8080; nginx inside the frontend container proxies `/api` to the backend. Put a TLS-terminating reverse proxy (Caddy, nginx, Traefik, ...) in front and set `SPOTIFY_REDIRECT_URI` and `FRONTEND_URL` to your public HTTPS URLs — Spotify OAuth will not work without it.

**Docker Swarm behind Traefik:** copy `docker-stack-traefik.example.yml` to `docker-stack-traefik.yml` (gitignored), fill in your domains and node hostnames, and deploy the stack. Afterwards:

```bash
./deploy.sh [backend|frontend|all]
```

rebuilds images, updates the Swarm services, and runs Alembic migrations inside the backend container.

## iOS Companion App

A native SwiftUI companion app lives in [`ios/`](ios/). It talks to the same backend — the server URL is configured at runtime on the login screen (or baked in as a build default via `ios/PodcastManager/Local.yml`). See [ios/CLAUDE.md](ios/CLAUDE.md) for build and signing setup.

## License

[GNU AGPL-3.0](LICENSE). You can use, modify, and self-host this freely — including for commercial purposes — but if you run a modified version as a network service, the AGPL requires you to offer its users the complete corresponding source. Contributions are accepted under the same license (see [CONTRIBUTING.md](CONTRIBUTING.md)).
