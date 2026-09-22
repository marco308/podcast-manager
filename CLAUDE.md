# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Podcast Manager is a self-hosted web app that sits on top of Spotify and adds a playlist-management layer. It syncs the user's subscribed Spotify podcasts, lets users assign podcasts directly to managed playlists, and keeps the corresponding Spotify playlists rebuilt automatically via background jobs. A native iOS companion app talks to the same backend.

## Repo Layout

- `ios/` — Native SwiftUI companion app (see `ios/CLAUDE.md` for iOS-specific guidance)
- `nimbalyst-local/plans/` — scratch planning notes, not shipped code

## Commands

### Backend (Python/FastAPI)

```bash
cd backend
source venv/bin/activate

# Migrations — Alembic owns the schema; the app never creates tables, so run this
# before serving locally (Docker's entrypoint.sh does it automatically)
alembic upgrade head

# Start server with HTTPS (required for Spotify OAuth; see mkcert setup below)
uvicorn app.main:app --reload \
  --ssl-keyfile=./certs/localhost+2-key.pem \
  --ssl-certfile=./certs/localhost+2.pem

```

### Local HTTPS Setup (Required for OAuth)

Spotify OAuth rejects `localhost` and non-HTTPS redirects. Generate certs with mkcert:

```bash
cd backend && mkdir -p certs && cd certs
mkcert -install
mkcert localhost 127.0.0.1 ::1
```

Use `127.0.0.1` (not `localhost`) in `SPOTIFY_REDIRECT_URI`.

- Deployment (`./deploy.sh`, Swarm, migrations, production hosts): see the `deploy` skill.

## Architecture

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

- Last-run times for interval jobs are tracked in the in-memory `_last_run_times` dict in `scheduler.py`; `daily_playlist_update` last-run comes from the `SyncLog` table instead.
- The cron schedule is mutable at runtime via `PUT /api/jobs/schedule`, persisted in the `app_settings` table (keys `playlist_update_hour`, `playlist_update_minute`) so restarts pick it up.

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

**SyncLog:** history of `playlist_update` and `cleanup` runs (status, details, timestamps). Consulted for "last run" (and its status) in `get_job_status()`. Jobs write a `RUNNING` row first and finalise it last; rows still `RUNNING` when the scheduler starts can only be from a process that died mid-run, so `init_scheduler` marks them `FAILED` with `failure_code="interrupted"` (issue #161).

**AppSetting:** key/value table used for runtime-mutable configuration (currently just the cron schedule).

## Environment Setup

Copy `backend/.env.example` to `backend/.env`. The non-obvious values:

```bash
SPOTIFY_REDIRECT_URI=https://127.0.0.1:8000/api/auth/callback   # 127.0.0.1, NOT localhost
ENCRYPTION_KEY=...   # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

- Spotify API constraints (removed batch endpoints, remaining endpoints, 429 handling): see the `spotify-api` skill.

## Testing

Backend tests live in `backend/tests/` (`unit/`, `integration/`, and `test_playlist_builder.py`) and run with pytest — `pip install -r requirements-dev.txt`, then `pytest tests` from `backend/`. `tests/conftest.py` injects dummy env vars, so no `.env` is needed. CI runs the suite plus ruff/ESLint/build checks on every PR. The frontend has no test suite beyond `npm run build`'s type-checking; the iOS `PodcastManagerTests` target has a couple of model-decoding tests (`xcodebuild test`, not run in CI).

## iOS Companion App

Non-trivial SwiftUI app living in `ios/`. When working on anything iOS-specific, read `ios/CLAUDE.md` — it covers the XcodeGen workflow, the gitignored `Local.yml` for signing/server-URL build overrides, TestFlight upload commands, keychain-backed auth, and the custom `Podcast` `Codable` handling for partial schemas. The backend server URL is configured at runtime on the login screen (falling back to the `DefaultServerURL` Info.plist value, if the build set one).
