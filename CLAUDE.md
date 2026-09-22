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

- Last-run times come from the `SyncLog` table for jobs that write it (`daily_playlist_update` → `playlist_update`, `remove_played_episodes` → `cleanup`; mapped in `_SYNCLOG_JOB_TYPES`), so they survive a restart. The other interval jobs fall back to the in-memory `_last_run_times` dict in `scheduler.py`.
- The cron schedule is mutable at runtime via `PUT /api/jobs/schedule`, persisted in the `app_settings` table (keys `playlist_update_hour`, `playlist_update_minute`) so restarts pick it up.

## Domain Concepts

**Playlist ↔ Podcast assignments:** many-to-many via `playlist_podcasts` (see `models/playlist_podcast.py`). The assignment row is where "what this show contributes to this playlist" lives (`docs/design/assignment-rules.md`, issue #249):
- `position` — per-playlist ordering, used when the playlist's `arrangement` is `by_position`
- `episode_limit` — `0` = all unplayed, `n` = at most n, `NULL` = inherit the playlist default
- `pick_from` — `newest` / `oldest`, `NULL` = inherit (sequential hint, then playlist default)

`services/assignment_rules.py::resolve_rule` is the single resolver used by both the builder and the API; the API returns the resolved `rule` and the raw `override` on every row so the UI shows exactly what the next build does. `PATCH /playlists/{id}/podcasts/{podcast_id}` sets or clears overrides (present-and-null clears, absent leaves alone via `model_fields_set`).

**Playlist settings:**
- `default_episode_limit`, `default_pick_from`: inherited by assignments without an override
- `arrangement`: `by_position` (concatenate groups in assignment order) or `by_date` (merge by release date in `date_direction`). In a `by_date` / `newest_first` playlist, a show whose rule resolved to `oldest` keeps the slots it won in the merge but fills them oldest-first, so a serial is never played out of order (`PlaylistBuilder.assemble`, the slot refill from issue #146). `newest` is only a preference and follows the playlist direction.
- `is_weekend_only`: on a day that isn't Fri/Sat/Sun or a UK public holiday, the playlist is **skipped entirely** — `update_playlist` returns early with `skipped=True` before any Spotify call, so the previous contents survive untouched. Holiday lookup is in `utils/holidays.py`. Note the gate lives in `update_playlist`, not `build_playlist`: an earlier version gated the build, which returned an empty list and — because `replace_playlist_items` is a full replace — *blanked* the playlist on weekdays (issue #150).
- `is_enabled`: jobs skip disabled playlists

**Fetching is proportional to the rule** (`PlaylistBuilder._fetch_unplayed`): a `newest` rule walks pages from offset 0 and stops once it has enough unplayed; an `oldest` rule reads `total` from the first page and walks backwards from the tail; an unlimited rule reads up to `MAX_EPISODES_PER_SHOW`. `podcast.unplayed_episodes` is only written when the walk saw the whole catalogue. It is `NULL` ("not counted") until then; `POST /podcasts/sync` never writes it and makes no per-show episode calls (issue #155).

**Podcast sync** (`POST /podcasts/sync`) upserts from `GET /me/shows` and retires podcasts that have left the library. Deleting one cascades to its assignments, so absence has to be earned: a show missing from a walk is marked (`podcasts.missing_since`) and only deleted once it has stayed missing for `UNSUBSCRIBE_GRACE` (7 days, `routers/podcasts.py`); reappearing clears the mark. Nothing is marked unless the walk looks like a whole snapshot — at least Spotify's reported `total` distinct shows, and a `total` that didn't move between pages (a library that shrinks mid-walk otherwise returns a short page whose smaller total the already-seen IDs satisfy). Orthogonal to `is_archived`: an archived show is still followed on Spotify, so it stays in the walk and is never marked.

**Podcast attribute:**
- `is_sequential`: story-based. A hint that resolves `pick_from` to `oldest` on every assignment unless the row overrides it.
- `is_archived`: hidden from the app (`GET /podcasts` leaves it out unless `include_archived=true`, so dashboard counts and assignment selects never see it) but still followed on Spotify. Archiving drops the podcast's assignments; unfollowing (`DELETE /podcasts/{id}`) stays a separate, destructive action (issue #247).


**Podcast routes are keyed by the integer `id`** (`/podcasts/{podcast_id}`), the same key as `/playlists/{id}/podcasts/{podcast_id}`. `_get_podcast_or_404` still resolves a non-numeric segment as a `spotify_id` so iOS builds predating the switch keep working; drop that fallback once they are gone (issue #248). `GET /podcasts` has no membership filters — both clients page the whole library and filter locally.

**Playlist ↔ Spotify:** `DELETE /playlists/{id}?remove_from_spotify=true` unfollows (= deletes) the Spotify playlist before removing the row; without it the Spotify playlist is left orphaned. A rename via `PATCH` is pushed to Spotify first (`PUT /playlists/{id}`); a Spotify failure saves nothing (502), a Spotify 404 renames locally only.

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
