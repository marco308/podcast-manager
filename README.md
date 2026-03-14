# Podcast Manager

A self-hosted web app that brings structure and automation to your Spotify podcast listening. It connects to your Spotify account, pulls in your subscribed podcasts, and lets you categorise them and define rules for how playlists should be built — then keeps those playlists updated automatically.

## The Problem

Spotify's podcast experience is a single chronological feed. If you subscribe to 30+ podcasts across different genres — daily news, long-form storytelling, casual background listening — they all land in the same pile. There's no way to say "give me today's news episodes in one playlist" or "build me a queue of my favourite shows, oldest episodes first."

## What This App Does

Podcast Manager sits on top of Spotify and adds a **categorisation + rules layer**. You tag your podcasts, define playlist rules, and the app continuously builds and maintains Spotify playlists for you.

### Core Workflow

1. **Sync** your Spotify podcast library into the app
2. **Categorise** each podcast (primary, news, background, weekend — or multiple)
3. **Set attributes** like sequential (oldest-first for story podcasts) or weekend-only
4. **Create managed playlists** with rules like "all unplayed primary episodes" or "latest news episode per show"
5. **The app handles the rest** — daily rebuilds, played-episode cleanup, token refresh

### Categories

| Category | Behaviour |
|----------|-----------|
| **Primary** | Your must-listen shows. All unplayed episodes included. |
| **News** | Time-sensitive content. Only the latest unplayed episode per show. |
| **Background** | Low-priority / filler. All unplayed episodes, but in a separate playlist. |
| **Weekend** | Only included on Fridays, Saturdays, Sundays, and UK public holidays. |

Podcasts can belong to multiple categories simultaneously.

### Podcast Attributes

- **Sequential** — Story-based podcasts that must be consumed oldest-to-newest (e.g. serialised true crime). Always ordered oldest-first regardless of playlist settings.
- **Weekend Only** — Episodes only appear in playlists on weekends and UK public holidays, regardless of category.
- **Playlist Order** — Manual ordering for podcasts within custom-ordered playlists.

### Playlist Rule Types

Each managed playlist has a rule type that determines which episodes it pulls in:

| Rule | What it does |
|------|-------------|
| **Primary** | All unplayed episodes from primary-category podcasts |
| **News** | Latest unplayed episode per news-category podcast |
| **Morning** | Same as news, but defaults to custom podcast ordering (commute playlist) |
| **Background** | All unplayed episodes from background-category podcasts |
| **Weekend** | All unplayed episodes from weekend-category podcasts |

### Ordering Modes

Each playlist can be ordered differently:

- **Default** — Category-appropriate (oldest-first for primary, newest-first for news)
- **Podcast Order** — Group by podcast, ordered by your manual ranking
- **Chronological (oldest first)** — All episodes by release date, ascending
- **Chronological (newest first)** — All episodes by release date, descending

Sequential podcasts always maintain oldest-first ordering within their group, regardless of the playlist's ordering mode.

## Automation

Once configured, the app runs four background jobs:

| Job | Schedule | What it does |
|-----|----------|-------------|
| **Playlist update** | Daily (configurable, default 4 AM) | Rebuilds all enabled playlists with current unplayed episodes |
| **Played episode cleanup** | Every 5 minutes | Removes fully-played episodes from all managed playlists |
| **Token refresh** | Every 45 minutes | Refreshes Spotify access tokens before they expire |
| **Session cleanup** | Every hour | Removes expired user sessions |

## Tech Stack

- **Backend:** FastAPI, async SQLAlchemy, SQLite, APScheduler
- **Frontend:** React 19, TypeScript, Vite, Ant Design
- **Auth:** Spotify OAuth2 with encrypted token storage (Fernet)
- **Deployment:** Docker Swarm behind Traefik reverse proxy

## Screenshots

The app has four main screens:

- **Dashboard** — Quick stats (total podcasts, categorisation progress, playlist status) and one-click sync/update buttons
- **Podcasts** — Searchable list with card and table views; inline category editing, sequential/weekend toggles, unfollow
- **Playlists** — Playlist CRUD with rule type and ordering config; drag-and-drop podcast reordering for custom-ordered playlists
- **Settings** — Spotify account info, theme selector (light/dark/system/auto)

## Setup

### Prerequisites

- Spotify Developer account with an app configured
- Docker (for deployment) or Python 3.11+ and Node.js (for local dev)

### Environment Variables

Copy `backend/.env.example` to `backend/.env` and configure:

```bash
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=https://127.0.0.1:8000/api/auth/callback
ENCRYPTION_KEY=...    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
SECRET_KEY=...        # python -c "import secrets; print(secrets.token_urlsafe(32))"
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
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload \
  --ssl-keyfile=./certs/localhost+2-key.pem \
  --ssl-certfile=./certs/localhost+2.pem

# Frontend
cd frontend
npm install
npm run dev
```

### Production Deployment

```bash
./deploy.sh [backend|frontend|all]
```

This builds Docker images, runs migrations, and updates the Swarm services. The app is served at `podcastmanager.marcuslab.uk` with the API at `api-podcastmanager.marcuslab.uk`.
