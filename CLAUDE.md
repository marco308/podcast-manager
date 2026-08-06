# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Podcast Manager is a self-hosted web app that sits on top of Spotify and adds a playlist-management layer. It syncs the user's subscribed Spotify podcasts, lets users assign podcasts directly to managed playlists, and keeps the corresponding Spotify playlists rebuilt automatically via background jobs. A native iOS companion app talks to the same backend.

## Repo Layout

- `backend/` — FastAPI + async SQLAlchemy + APScheduler (Python 3.11+ supported; CI and the Docker image run 3.14)
- `frontend/` — React 19 + TypeScript + Vite + Ant Design 6
- `ios/` — Native SwiftUI companion app (see `ios/CLAUDE.md` for iOS-specific guidance)
- `docker-compose.yml` — single-host deployment; `deploy.sh` + `docker-stack-traefik.example.yml` — Docker Swarm deployment behind Traefik (copy the example to the gitignored `docker-stack-traefik.yml` and fill in your domains)

## Commands

### Backend (Python/FastAPI)

```bash
cd backend
source venv/bin/activate

# Start server with HTTPS (required for Spotify OAuth; see mkcert setup below)
uvicorn app.main:app --reload \
  --ssl-keyfile=./certs/localhost+2-key.pem \
  --ssl-certfile=./certs/localhost+2.pem

# Lint / format (ruff, configured in backend/pyproject.toml)
ruff check app
ruff format app

# Tests (pytest + pytest-asyncio; install via requirements-dev.txt)
pytest tests

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
```

SQLite DB lives at `backend/data/podcast_manager.db` (path from `DATABASE_URL`).

**Alembic owns the schema.** The app does not create tables at startup — run `alembic upgrade head` before serving locally. In Docker, `backend/entrypoint.sh` does it for you. Databases created by the old `create_all` startup path (tables, but no `alembic_version` row) are adopted automatically by `scripts/adopt_legacy_schema.py`, which stamps them at head so migrations can proceed.

### Frontend (React/Vite)

```bash
cd frontend
npm install
npm run dev           # Vite dev server
npm run build         # tsc -b && vite build
npm run lint          # ESLint
npm run format        # Prettier write
npm run format:check  # Prettier check
```

### Local HTTPS Setup (Required for OAuth)

Spotify OAuth rejects `localhost` and non-HTTPS redirects. Generate certs with mkcert:

```bash
cd backend && mkdir -p certs && cd certs
mkcert -install
mkcert localhost 127.0.0.1 ::1
```

Use `127.0.0.1` (not `localhost`) in `SPOTIFY_REDIRECT_URI`.

### Deployment

```bash
./deploy.sh [backend|frontend|all]
```

Builds Docker images and updates the Swarm services. Migrations run automatically in the container entrypoint (`backend/entrypoint.sh`) before uvicorn starts, so both this path and `docker compose up -d --build` get a migrated database. Assumes a stack deployed from your (gitignored) copy of `docker-stack-traefik.example.yml`.

## Architecture

### Stack

- **Backend:** FastAPI, async SQLAlchemy, SQLite (aiosqlite), APScheduler, Pydantic Settings
- **Frontend:** React 19, TypeScript, Vite, Ant Design 6, React Query, axios, dnd-kit
- **Auth:** Spotify OAuth2 Authorization Code + httpOnly cookie session + CSRF double-submit
- **Secrets:** Access/refresh tokens encrypted at rest with Fernet (`services/encryption.py`)

### Authentication Flow (important — this is cookie-based, not query-param)

1. Frontend hits `/api/auth/login`; backend redirects to Spotify with an OAuth `state` stored in a short-lived `oauth_state` cookie.
2. On callback, backend creates a `Session` row, issues two cookies:
   - `session_id` — httpOnly, Secure, SameSite=Lax
   - `csrf_token` — readable by JS (not httpOnly)
3. Axios client (`frontend/src/api/client.ts`) uses `withCredentials: true`. A request interceptor reads `csrf_token` from `document.cookie` and adds `X-CSRF-Token` header for POST/PUT/PATCH/DELETE.
4. On 401 the interceptor redirects to `/login`; on 403 CSRF failure it re-reads the cookie and retries once.
5. Cookies can be scoped cross-subdomain via `COOKIE_DOMAIN` env (e.g. `.example.com`).

The iOS app does OAuth via `ASWebAuthenticationSession` and a `redirect_scheme=podcastmanager` query param; backend redirects to `podcastmanager://auth/callback?code=...` with a single-use exchange code, which the app trades for real credentials via `POST /api/auth/mobile-exchange`. Session ID and CSRF token are stored in Keychain and sent as `Cookie` + `X-CSRF-Token` headers.

### Background Jobs (APScheduler)

Registered in `app/jobs/scheduler.py`, started from the FastAPI lifespan context:

| Job ID | Trigger | Purpose |
|---|---|---|
| `daily_playlist_update` | Cron, hour/minute from `AppSetting` or `PLAYLIST_UPDATE_HOUR/MINUTE` env | Rebuild every enabled playlist for every user |
| `token_refresh` | Every 45 min | Refresh Spotify tokens expiring within 15 min |
| `remove_played_episodes` | Every 30 min | Fetch playlist tracks and drop any whose `resume_point.fully_played` is set — filtered inline from the playlist-items `fields` mask, no per-episode fetch |
| `session_cleanup` | Every hour | Delete expired `Session` rows |

- Last-run times for interval jobs are tracked in the in-memory `_last_run_times` dict in `scheduler.py`; `daily_playlist_update` last-run comes from the `SyncLog` table instead.
- The cron schedule is mutable at runtime via `PUT /api/jobs/schedule`, persisted in the `app_settings` table (keys `playlist_update_hour`, `playlist_update_minute`) so restarts pick it up.

### API Endpoints

Routers are all mounted under `/api`:

- `/api/auth/*` — Spotify OAuth (login, callback, me, logout)
- `/api/podcasts/*` — CRUD + sync from Spotify
- `/api/playlists/*` — Playlist CRUD + manual rebuild triggers
- `/api/jobs/*` — Scheduler status + reschedule
- `/api/health` — Health check
- `/api/docs`, `/api/redoc`, `/api/openapi.json` — OpenAPI UI

List endpoints return `{ items: [], total: N }`.

### Backend Structure

```
backend/app/
├── main.py              # FastAPI app, lifespan (init_scheduler), CORS, routers
├── config.py            # Pydantic Settings (loads .env)
├── database.py          # Async SQLAlchemy engine/session (Alembic owns the schema)
├── models/              # SQLAlchemy ORM: user, session, podcast, playlist,
│                        #   playlist_podcast (M2M), sync_log, settings (AppSetting)
├── schemas/             # Pydantic request/response schemas
├── routers/             # auth, podcasts, playlists, jobs
├── services/
│   ├── spotify.py           # SpotifyService, _request_with_retry, concurrency-limited fetches
│   ├── playlist_builder.py  # PlaylistBuilder — builds/updates a user's playlists
│   ├── session.py           # SessionService — session/CSRF issuance & validation
│   └── encryption.py        # Fernet wrapper for token at-rest encryption
├── jobs/
│   ├── scheduler.py         # APScheduler setup + job functions
│   └── session_cleanup.py
└── utils/               # e.g. holidays.py (UK public holidays for weekend-only playlists)
```

### Frontend Structure

```
frontend/src/
├── api/          # axios client (withCredentials, CSRF interceptor) + per-resource wrappers
├── components/   # Layout, PodcastTable, common
├── context/      # AuthContext
├── hooks/        # usePodcasts, usePlaylists, useJobs (React Query)
├── pages/        # Login, Dashboard, Podcasts, Playlists, Settings
├── theme/        # Ant Design theme config (light/dark/system/auto)
└── types/        # TypeScript definitions
```

## Domain Concepts

**Playlist ↔ Podcast assignments:** many-to-many via `playlist_podcasts` (see `models/playlist_podcast.py`); each row has an optional `position` for per-playlist ordering. A podcast can sit in multiple playlists with independent positions.

**Playlist settings:**
- `episode_mode`: `all_unplayed` (every unplayed episode) or `latest_only` (newest unplayed per podcast)
- `is_weekend_only`: on a day that isn't Fri/Sat/Sun or a UK public holiday, the playlist is **skipped entirely** — `update_playlist` returns early with `skipped=True` before any Spotify call, so the previous contents survive untouched. Holiday lookup is in `utils/holidays.py`. Note the gate lives in `update_playlist`, not `build_playlist`: an earlier version gated the build, which returned an empty list and — because `replace_playlist_items` is a full replace — *blanked* the playlist on weekdays (issue #150).
- `ordering_mode`: `default`, `podcast_order`, `chronological_asc`, `chronological_desc`
- `is_enabled`: jobs skip disabled playlists

**Podcast attribute:**
- `is_sequential`: story-based, always ordered oldest-first regardless of playlist `ordering_mode`

**Single-user by construction:** `auth.py` closes registration once one `User` row exists, so the deployment has exactly one user. Consequently `podcasts` is a **deliberately global table** — it has no `user_id`, and the podcast routes do not filter by owner. `playlists` *is* user-scoped (it predates the decision and the column is harmless), but nothing depends on that scoping for security. If multi-user is ever wanted, adding `Podcast.user_id` and filtering every podcast route is a prerequisite, not an optimisation (issue #154).

**SyncLog:** history of `playlist_update` runs (status, details, timestamps). Consulted for "last run" in `get_job_status()`.

**AppSetting:** key/value table used for runtime-mutable configuration (currently just the cron schedule).

## Environment Setup

Copy `backend/.env.example` to `backend/.env`:

```bash
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=https://127.0.0.1:8000/api/auth/callback   # 127.0.0.1, NOT localhost
ENCRYPTION_KEY=...   # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FRONTEND_URL=https://127.0.0.1:3000
COOKIE_DOMAIN=       # empty for local; ".example.com"-style value in prod
PLAYLIST_UPDATE_HOUR=4
PLAYLIST_UPDATE_MINUTE=0
DEBUG=false
```

Spotify scopes requested: `user-read-playback-position`, `user-library-read`, `user-library-modify`, `playlist-modify-public`, `playlist-modify-private`.

## Spotify API Constraints

**API docs:** https://developer.spotify.com/documentation/web-api

**Dev Mode batch-endpoint removal (Feb/Mar 2026):** Spotify removed the following for Dev Mode apps:
- `GET /episodes` (batch by IDs) — **removed**
- `GET /shows` (batch by IDs) — **removed**
- All other "Get Several X" batch endpoints — **removed**

**Still available and in use:**
- `GET /shows/{id}/episodes` — paginated show episodes
- `GET /me/shows` — user's subscribed podcasts (primary sync source)
- `GET /me/episodes` — user's saved episodes
- All playlist and user-profile endpoints

**Rate limiting:** Spotify 429s carry a `Retry-After`. `SpotifyService._request_with_retry()` issues up to 3 attempts total (1 + 2 retries); every request goes through it. A per-instance sliding-window soft throttle backs off before Spotify has to 429 us, and the `remove_played_episodes` job additionally runs under a per-run API-call budget (`CLEANUP_API_CALL_BUDGET`).

## Testing

Backend tests live in `backend/tests/` (`unit/`, `integration/`, and `test_playlist_builder.py`) and run with pytest — `pip install -r requirements-dev.txt`, then `pytest tests` from `backend/`. `tests/conftest.py` injects dummy env vars, so no `.env` is needed. CI runs the suite plus ruff/ESLint/build checks on every PR. The frontend has no test suite beyond `npm run build`'s type-checking; the iOS `PodcastManagerTests` target has a couple of model-decoding tests (`xcodebuild test`, not run in CI).

## iOS Companion App

Non-trivial SwiftUI app living in `ios/`. When working on anything iOS-specific, read `ios/CLAUDE.md` — it covers the XcodeGen workflow, the gitignored `Local.yml` for signing/server-URL build overrides, TestFlight upload commands, keychain-backed auth, and the custom `Podcast` `Codable` handling for partial schemas. The backend server URL is configured at runtime on the login screen (falling back to the `DefaultServerURL` Info.plist value, if the build set one).
