# Copilot Instructions for Podcast Manager

**Project:** Podcast Manager - Web app for managing podcast subscriptions with Spotify integration and automated playlist generation.

## Architecture Overview

```
Frontend (React/TypeScript/Vite) ←→ Backend (FastAPI/Python) ←→ Spotify Web API
                ↓ Session via localStorage
        SQLite (Docker volume)
```

**Key Pattern:** Session-based auth instead of JWT. Frontend stores session ID in localStorage, appends `?session=xxx` to all API requests via axios interceptor. Tokens encrypted at rest with Fernet.

## Critical Workflows

### Backend Setup & Running

```bash
cd backend
python -m venv venv          # Create if missing
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head         # Apply migrations

# HTTPS required for Spotify OAuth (use mkcert)
./venv/bin/uvicorn app.main:app --reload \
  --ssl-keyfile=./certs/localhost+2-key.pem \
  --ssl-certfile=./certs/localhost+2.pem
```

**Important:** Always use `127.0.0.1` in `SPOTIFY_REDIRECT_URI` (not `localhost`) to avoid Spotify OAuth errors.

### Frontend Setup & Running

```bash
cd frontend
npm install
npm run dev           # Dev server on port 3000
npm run build         # Production build
npm run lint          # ESLint check
npx tsc --noEmit      # TypeScript check
```

### Database Migrations

Create: `alembic revision --autogenerate -m "description"`
Apply: `alembic upgrade head`

## Backend Architecture Essentials

### File Structure & Responsibilities

| Path                    | Purpose                                                       |
| ----------------------- | ------------------------------------------------------------- |
| `app/main.py`           | FastAPI app, CORS, lifespan hooks, exception handlers         |
| `app/config.py`         | Pydantic settings from `.env` (cached with `@lru_cache`)      |
| `app/database.py`       | Async SQLAlchemy engine, Base class, `get_db()` dependency    |
| `app/models/`           | SQLAlchemy ORM models (User, Podcast, Playlist, SyncLog)      |
| `app/schemas/`          | Pydantic request/response validation schemas                  |
| `app/routers/`          | API endpoints organized by domain (auth, podcasts, playlists) |
| `app/services/`         | Business logic (Spotify API, encryption, playlist building)   |
| `app/jobs/scheduler.py` | APScheduler for daily playlist updates at 4 AM UTC            |
| `app/utils/holidays.py` | UK public holiday detection for `is_weekend_only` logic       |

### API Response Pattern

All list endpoints return: `{ "items": [...], "total": N }`
Frontend extracts `items` array using destructuring or indexing.

### Core Models & Constraints

**Podcast Categories** (in `app/models/podcast.py`):

- `primary`: Most important podcasts (included in all playlists)
- `news`: Time-sensitive (only latest unplayed episodes)
- `background`: Filler content (optional in playlists)
- `none`: Uncategorized (default)

**Podcast Attributes**:

- `is_sequential`: Story-based, must consume oldest-to-newest
- `is_weekend_only`: Only added Fri/Sat/Sun or UK holidays (computed in `app/utils/holidays.py`)

### Authentication Flow

1. Frontend redirects to `/api/auth/login` → Spotify auth URL
2. Spotify redirects to `/api/auth/callback?code=xxx`
3. Backend exchanges code for tokens via `SpotifyService.exchange_code_for_tokens()`
4. Tokens encrypted with Fernet, user created/updated in DB
5. Session ID (random, 32-char) stored in `_sessions` dict, returned in redirect query param
6. Frontend extracts session from URL query, stores in localStorage
7. All subsequent requests include `?session=xxx` (via axios interceptor)

**Session Store:** Currently in-memory dict `_sessions` (not production-ready; consider Redis for scale).

### Token Management (Critical)

- **Access tokens** encrypted before storing: `encryption.encrypt(token_data["access_token"])`
- **Refresh tokens** decrypted on-demand: `encryption.decrypt(self._user.refresh_token)`
- **Token expiry** checked in `PlaylistBuilder._get_spotify_client()` before API calls
- **Refresh logic** in `SpotifyService.refresh_access_token()`

### Spotify Integration Points

- `SpotifyService` (in `app/services/spotify.py`): Async HTTP client using `httpx`
  - `exchange_code_for_tokens()`: OAuth token exchange
  - `get_current_user()`: User profile
  - `get_saved_shows()`: User's podcast library (pagination via `limit`, `offset`)
  - `get_show_episodes()`: Episodes of a show
  - `create_playlist()` / `add_tracks_to_playlist()`: Playlist management
- `PlaylistBuilder` (in `app/services/playlist_builder.py`): Builds playlist content based on rules
  - Queries DB for podcasts by category
  - Filters episodes (sequential, weekend-only, unplayed)
  - Calls Spotify API to add episodes to playlists

### Background Jobs (APScheduler)

- **Daily playlist update**: Runs at 4 AM UTC (configurable via `PLAYLIST_UPDATE_HOUR`, `PLAYLIST_UPDATE_MINUTE`)
- Job registration in `app/jobs/scheduler.py`: `init_scheduler()` on app startup, `shutdown_scheduler()` on shutdown
- No retry logic by default; failed jobs logged but not re-queued

## Frontend Architecture Essentials

### File Structure & Responsibilities

| Path                                             | Purpose                                                           |
| ------------------------------------------------ | ----------------------------------------------------------------- |
| `src/api/client.ts`                              | Axios instance with session interceptor & error handling          |
| `src/api/auth.ts`, `podcasts.ts`, `playlists.ts` | API service functions (one file per domain)                       |
| `src/context/AuthContext.tsx`                    | Global auth state: user, isAuthenticated, login/logout methods    |
| `src/hooks/usePodcasts.ts`, `usePlaylists.ts`    | React Query hooks for server state + optimistic updates           |
| `src/components/Layout/`                         | Header, Sidebar, MainLayout wrapper                               |
| `src/components/PodcastTable/`                   | Podcast list with categorization & attribute toggles              |
| `src/pages/`                                     | Page components (Login, Dashboard, Podcasts, Playlists, Settings) |
| `src/types/index.ts`                             | TypeScript interfaces (User, Podcast, Playlist, etc.)             |

### Authentication & Session Management

**AuthContext** (`src/context/AuthContext.tsx`):

- `useAuth()` hook provides: `user`, `isAuthenticated`, `isLoading`, `login()`, `logout()`, `refetch()`
- Session check on app load: extracts from URL query (OAuth callback) or localStorage
- User fetch only triggered if session exists (`enabled: hasSession`)
- 5-minute stale time for `/api/auth/me` query

**Session Flow:**

1. OAuth callback redirects to `/?session=xxx`
2. `App.tsx` extracts session from URL, stores in localStorage, clears URL
3. AuthContext queries `/api/auth/me?session=xxx`
4. Subsequent requests auto-append session via axios interceptor

### React Query Setup

- **Query keys**: Hierarchical (`['podcasts', 'list']`, `['playlists', playlistId]`)
- **Mutations**: Use `onSuccess` callbacks to invalidate queries or update cache
- **Optimistic updates**: `setQueryData()` before API call, rollback on error
- **Error handling**: Global via axios interceptor (401 redirects to login)

### Podcast Categorization UI

Component: `src/components/PodcastTable/PodcastTable.tsx`

- Dropdown to set category: `primary`, `news`, `background`, `none`
- Toggles for `is_sequential`, `is_weekend_only`
- Tags display current state (color-coded by category)
- Mutation on change: `useMutation()` to PATCH `/api/podcasts/{id}`

## Critical Decisions & Gotchas

1. **Session instead of JWT**: Tokens stored server-side in memory (not scalable). Consider Redis for production.
2. **Fernet encryption**: Tokens encrypted with `cryptography.Fernet`. Key must be valid base64 string from `secrets.token_urlsafe(32)`.
3. **SQLite in Docker**: Data persisted via volume mount to `./data/`. No password auth.
4. **HTTPS for development**: Spotify OAuth requires HTTPS. Generated certs via mkcert (not production-ready).
5. **Token refresh**: Happens lazily in `PlaylistBuilder` before Spotify API calls, not proactively.
6. **No batch operations**: Playlist building loops and adds episodes one-by-one (could optimize with Spotify batch API).
7. **APScheduler in-process**: Runs in same process as FastAPI. No distributed job support.

## Common Tasks

### Adding a new API endpoint

1. Create Pydantic schema in `app/schemas/` (request/response)
2. Define router function in `app/routers/` with `@router.get/post/patch/delete` decorator
3. Use `Depends(get_db)` and `Depends(get_current_user_id)` for dependencies
4. Call service layer from `app/services/` for business logic
5. Return Pydantic response model for auto-validation & OpenAPI docs

### Adding a new podcast attribute

1. Add field to `Podcast` model in `app/models/podcast.py` (with SQLAlchemy type & nullable)
2. Create Alembic migration: `alembic revision --autogenerate -m "add podcast field"`
3. Update `PodcastResponse` schema in `app/schemas/podcast.py`
4. Update UI in `src/components/PodcastTable/` to display/edit field
5. Add to React Query mutation payload in `src/hooks/usePodcasts.ts`

### Running Docker Compose

```bash
docker compose up -d --build    # Build & start containers
docker compose logs -f backend  # Stream backend logs
docker compose down             # Stop & remove
```

Frontend runs on port 3000, backend on 8000 (both inside Docker network).

## Environment Variables (.env)

```bash
SPOTIFY_CLIENT_ID=xxx
SPOTIFY_CLIENT_SECRET=xxx
SPOTIFY_REDIRECT_URI=https://127.0.0.1:8000/api/auth/callback
ENCRYPTION_KEY=<base64 Fernet key>
SECRET_KEY=<random 32-char string>
FRONTEND_URL=https://localhost:3000
DATABASE_URL=sqlite+aiosqlite:///./data/podcast_manager.db
DEBUG=False
```

Generate keys: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## Key Files for Reference

- **OAuth flow**: [auth.py](../backend/app/routers/auth.py#L1)
- **Spotify service**: [spotify.py](../backend/app/services/spotify.py#L1)
- **Playlist builder logic**: [playlist_builder.py](../backend/app/services/playlist_builder.py#L1)
- **Database models**: [app/models/](../backend/app/models/)
- **Frontend API client**: [client.ts](../frontend/src/api/client.ts#L1)
- **AuthContext**: [AuthContext.tsx](../frontend/src/context/AuthContext.tsx#L1)
- **Tech plan**: [technical_implementation_plan_v2.md](../docs/technical_implementation_plan_v2.md#L1)
