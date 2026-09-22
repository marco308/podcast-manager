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

- `daily_playlist_update` runs `sync_all_libraries()` **first**, then rebuilds playlists (issue #240). The sync writes its own `library_sync` SyncLog row and its failures never abort the rebuild — a stale library beats a day with no playlist update. It runs outside `playlist_write_lock` (it only touches `podcasts`) but holds `library_sync_lock`.
- Last-run times come from the `SyncLog` table for jobs that write it, so they survive a restart; the other interval jobs fall back to the in-memory `_last_run_times` dict in `scheduler.py`. `_SYNCLOG_JOB_TYPES` maps a scheduler job id to **all** the job types its run writes — `daily_playlist_update` → `("playlist_update", "library_sync")`, `remove_played_episodes` → `("cleanup",)`. `get_job_status` dates the run from the newest step and reports the **worst** step's status, naming the failures in `last_run_failed_steps`: the UI shows one line per job, so a failed library sync under a successful rebuild would otherwise render as a clean run.
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
- There is no weekend-only setting. It existed until issue #238 and only froze a playlist Monday to Thursday; since every rebuild is a full replace from unplayed state, Friday's playlist came out the same either way. It was removed rather than renamed. `PlaylistResponse` still sends `is_weekend_only: false` because installed iOS builds require the field; drop it once those builds are gone.
- `is_enabled`: one rule, enforced in the backend (issue #239) — a disabled playlist is **never written to on Spotify**. The daily rebuild and `update_all_playlists` filter it out, the cleanup job skips it, `update_playlist` gates on it before any Spotify call, and `POST /playlists/{id}/run` refuses it with a 409. Both UIs disable Run and say so. Its Spotify playlist keeps whatever it last had until it is re-enabled.
- `spotify_playlist_id`: empty means one is created on the first run. Linking an existing playlist goes through `_check_spotify_playlist_link` in `routers/playlists.py`: the user must own it (`GET /playlists/{id}` owner vs `User.spotify_id`) and it can't already be linked to another managed playlist, because every rebuild fully replaces its contents. The form picks from `GET /api/playlists/spotify-playlists` (owned playlists only) rather than taking a free-text ID (issue #245). `PATCH` follows the override convention — present-and-null unlinks (the Spotify playlist is left in place), absent leaves the link alone. The pre-check is racy on its own, so `uq_playlists_user_spotify_playlist` (migration 016) is the real guarantee and `_commit_playlist` turns its `IntegrityError` into a 409. Listing and checking private playlists needs the `playlist-read-private` scope, added in #245 — tokens issued before that need a fresh login.

**Fetching is proportional to the rule** (`PlaylistBuilder._fetch_unplayed`): a `newest` rule walks pages from offset 0 and stops once it has enough unplayed; an `oldest` rule reads `total` from the first page and walks backwards from the tail; an unlimited rule reads up to `MAX_EPISODES_PER_SHOW`. `podcast.unplayed_episodes` is only written when the walk saw the whole catalogue. It is `NULL` ("not counted") until then; `POST /podcasts/sync` never writes it and makes no per-show episode calls (issue #155).

**Podcast sync** (`services/library_sync.py::sync_library`, shared by `POST /podcasts/sync` and the daily job) upserts from `GET /me/shows` and retires podcasts that have left the library. Deleting one cascades to its assignments, so absence has to be earned: a show missing from a walk is marked (`podcasts.missing_since`) and only deleted once it has stayed missing for `UNSUBSCRIBE_GRACE` (7 days, `services/library_sync.py`); reappearing clears the mark. A marked show also stops contributing episodes immediately — `PlaylistBuilder._get_playlist_podcasts` filters it out — rather than serving episodes from an unsubscribed show for the whole grace period (issue #240). Its assignments are untouched, so a show that comes back inside the grace period returns to its playlists exactly as it was. Nothing is marked unless the walk looks like a whole snapshot — at least Spotify's reported `total` distinct shows, and a `total` that didn't move between pages (a library that shrinks mid-walk otherwise returns a short page whose smaller total the already-seen IDs satisfy). Orthogonal to `is_archived`: an archived show is still followed on Spotify, so it stays in the walk and is never marked.

**Podcast attributes:**
- `is_sequential`: story-based. A hint that resolves `pick_from` to `oldest` on every assignment unless the row overrides it.
- `is_archived`: hidden from the app (`GET /podcasts` leaves it out unless `include_archived=true`, so dashboard counts and assignment selects never see it) but still followed on Spotify. Archiving drops the podcast's assignments; unfollowing (`DELETE /podcasts/{id}`) stays a separate, destructive action (issue #247).
- `missing_since`: set by the sync when the show has left the Spotify library (issue #155). Unlike archiving, the podcast stays *visible* — with a "Not on Spotify" tag and the date — and keeps its assignments, but it contributes no episodes from that moment and the row is deleted at the end of the grace period.

**Library sync invariants** (`services/library_sync.py`):
- A walk that raises part-way through reconciles nothing (the reconcile only runs after the loop) and the caller rolls back, so a half-read never becomes a half-library.
- Nothing is marked unless the walk looked like a snapshot; when it didn't, `LibrarySyncResult.reconciled` is False, surfaced as `reconcile_skipped` on the endpoint and reported by the UI as a warning rather than a success (the counts don't mean what they usually mean).
- Syncs are serialised on `locks.library_sync_lock`, **held across the commit**. Two concurrent walks both see "no row" for a newly-followed show and both insert it; the loser's commit then dies on the `spotify_id` unique constraint and sinks the whole sync — the cross-request twin of the intra-request duplicate from issue #182. Releasing before the commit would leave the pending insert invisible and reopen the race. The job waits for the lock; `POST /podcasts/sync` gives up after `SYNC_LOCK_WAIT_SECONDS` and returns 409, since a second full walk would only redo the same work.

**Podcast routes are keyed by the integer `id`** (`/podcasts/{podcast_id}`), the same key as `/playlists/{id}/podcasts/{podcast_id}`. `_get_podcast_or_404` still resolves a non-numeric segment as a `spotify_id` so iOS builds predating the switch keep working; drop that fallback once they are gone (issue #248). `GET /podcasts` has no membership filters — both clients page the whole library and filter locally.

**Playlist ↔ Spotify:** `DELETE /playlists/{id}?remove_from_spotify=true` unfollows (= deletes) the Spotify playlist before removing the row; without it the Spotify playlist is left orphaned. A rename via `PATCH` is pushed to Spotify first (`PUT /playlists/{id}`); a Spotify failure saves nothing (502), a Spotify 404 renames locally only.

**Single-user by construction:** `auth.py` closes registration once one `User` row exists, so the deployment has exactly one user. Consequently `podcasts` is a **deliberately global table** — it has no `user_id`, and the podcast routes do not filter by owner. `playlists` *is* user-scoped (it predates the decision and the column is harmless), but nothing depends on that scoping for security. If multi-user is ever wanted, adding `Podcast.user_id` and filtering every podcast route is a prerequisite, not an optimisation (issue #154).

**Migration chain:** one linear chain, one head — `alembic upgrade head` fails outright on two, including in the Docker entrypoint. Two branches off the same parent will do that, and it has happened twice (#250/#251, then #253/#254). The fix is to relink the later-merged migration's `down_revision` onto the other head, not to leave both. `016_playlist_spotify_link_unique` revises `017_podcast_missing_since` for that reason: its file name and revision id record when it was written, not its place in the chain, because renaming a revision id would orphan any database stamped at it.

**SyncLog:** history of `playlist_update`, `library_sync` and `cleanup` runs (status, details, timestamps). Consulted for "last run" (and its status) in `get_job_status()`. Jobs write a `RUNNING` row first and finalise it last; rows still `RUNNING` when the scheduler starts can only be from a process that died mid-run, so `init_scheduler` marks them `FAILED` with `failure_code="interrupted"` (issue #161).

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
