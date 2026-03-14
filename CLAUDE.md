# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Podcast Manager is a web application for managing podcast subscriptions with custom categorization and automated playlist generation. It integrates with Spotify to sync podcasts and create playlists based on user-defined rules.

**Current Status:** Phase 1 (Foundation & Auth) complete, Phase 2 (Podcast Sync & Management) complete.

## Commands

### Backend (Python/FastAPI)

```bash
cd backend
source venv/bin/activate

# Start server with HTTPS (required for Spotify OAuth)
uvicorn app.main:app --reload \
  --ssl-keyfile=./certs/localhost+2-key.pem \
  --ssl-certfile=./certs/localhost+2.pem

# Run database migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"
```

### Frontend (React/Vite)

```bash
cd frontend
npm install
npm run dev      # Start dev server (port 3000)
npm run build    # Build for production
npm run lint     # Run ESLint
```

### Local HTTPS Setup (Required)

Spotify OAuth requires HTTPS. Generate certificates with mkcert:

```bash
cd backend && mkdir -p certs && cd certs
mkcert -install
mkcert localhost 127.0.0.1 ::1
```

## Architecture

### Stack

- **Backend:** FastAPI + async SQLAlchemy + SQLite + APScheduler
- **Frontend:** React 19 + TypeScript + Vite + Ant Design 6 + React Query

### Key Patterns

**Authentication Flow:**
- Spotify OAuth2 Authorization Code Flow
- Backend generates session ID on OAuth callback
- Frontend stores session in localStorage
- Axios interceptor appends `?session=xxx` to all API requests
- Tokens encrypted at rest with Fernet

**API Response Pattern:**
- List endpoints return `{ items: [], total: N }`
- Frontend extracts `items` array from response

**Frontend State:**
- React Query for server state with optimistic updates
- AuthContext for session management

### Backend Structure

```
backend/app/
├── main.py              # FastAPI app, CORS, routers
├── config.py            # Pydantic settings from .env
├── database.py          # Async SQLAlchemy engine/session
├── models/              # SQLAlchemy ORM models
├── schemas/             # Pydantic request/response schemas
├── routers/             # API endpoints (auth, podcasts, playlists)
├── services/            # Business logic (spotify.py, encryption.py)
├── jobs/                # APScheduler background jobs
└── utils/               # Helpers (holidays.py for UK public holidays)
```

### Frontend Structure

```
frontend/src/
├── api/                 # Axios client + API functions
├── components/          # Layout, PodcastTable, common
├── context/             # AuthContext with session management
├── hooks/               # usePodcasts, usePlaylists (React Query)
├── pages/               # Login, Dashboard, Podcasts, Playlists, Settings
└── types/               # TypeScript definitions
```

### API Endpoints

- `/api/auth/*` - Spotify OAuth (login, callback, me, logout)
- `/api/podcasts/*` - CRUD + sync from Spotify
- `/api/playlists/*` - Playlist management + manual triggers

## Domain Concepts

**Podcast Categories:** primary, news, background, none
- Primary: Most important podcasts
- News: Time-sensitive, only latest episode matters
- Background: Filler content

**Podcast Attributes:**
- `is_sequential`: Story-based, must be consumed oldest-to-newest
- `is_weekend_only`: Only added to playlists on Fri/Sat/Sun or UK holidays

## Environment Setup

Copy `backend/.env.example` to `backend/.env` and configure:

```bash
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=https://127.0.0.1:8000/api/auth/callback
ENCRYPTION_KEY=...  # Generate with Fernet.generate_key()
SECRET_KEY=...      # Generate with secrets.token_urlsafe(32)
```

**Important:** Use `127.0.0.1` (not `localhost`) in redirect URI to avoid Spotify OAuth errors.

## Spotify API Constraints

**API Docs:** https://developer.spotify.com/documentation/web-api

**Dev Mode Restrictions (Feb/Mar 2026):** Spotify removed batch endpoints for Dev Mode apps:
- `GET /episodes` (batch by IDs) — **removed**
- `GET /shows` (batch by IDs) — **removed**
- All other "Get Several X" batch endpoints — **removed**

**Still available:**
- `GET /episodes/{id}` — single episode fetch (used via `get_episodes()` with concurrency control)
- `GET /shows/{id}/episodes` — paginated show episodes
- `GET /me/shows` — user's subscribed podcasts (primary sync endpoint)
- `GET /me/episodes` — user's saved episodes
- All playlist endpoints, user profile, etc.

**Rate limiting:** Spotify returns 429 with a `Retry-After` header. `SpotifyService._request_with_retry()` handles this automatically with up to 3 retries. All loop-called methods use this helper. Keep concurrency low (semaphore of 3) for individual episode fetches.
