# Podcast Manager

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm_Noncommercial_1.0.0-red.svg)](LICENSE)

A self-hosted web app that brings structure and automation to your Spotify podcast listening. It connects to your Spotify account, pulls in your subscribed podcasts, and lets you assign them directly to managed playlists — then keeps those playlists updated automatically.

## The Problem

Spotify's podcast experience is a single chronological feed. If you subscribe to 30+ podcasts across different genres — daily news, long-form storytelling, casual background listening — they all land in the same pile. There's no way to say "give me today's news episodes in one playlist" or "build me a queue of my favourite shows, oldest episodes first."

## What This App Does

Podcast Manager sits on top of Spotify and adds a **playlist management layer**. You create playlists, assign podcasts to them, and the app continuously builds and maintains the corresponding Spotify playlists for you.

### Core Workflow

1. **Sync** your Spotify podcast library into the app
2. **Create playlists** with defaults for how many episodes each show contributes and how they are arranged
3. **Assign podcasts** directly to one or more playlists
4. **Refine** individual assignments where a show needs a different rule, and mark story podcasts as sequential
5. **The app handles the rest** — daily rebuilds, played-episode cleanup, token refresh

### Episode Rules

What a show contributes is decided **per assignment** (podcast × playlist), so the same show can behave differently in different playlists. Every playlist carries defaults; a row inherits them until you refine it. See [docs/design/assignment-rules.md](docs/design/assignment-rules.md).

| Rule | Values | Meaning |
|------|--------|---------|
| **Episodes per podcast** | all unplayed / latest only / up to *n* | How many unplayed episodes the show contributes |
| **Take from** | newest / oldest | Which end of the show's unplayed episodes to take from, and the order they are listened to |

Precedence: the row's own override, then the podcast's **Sequential** flag (forces *oldest*), then the playlist default.

Example — a Morning playlist with defaults "latest only, newest": each daily news show contributes today's episode, and a story podcast marked sequential contributes its *next unfinished* episode instead, with no per-row configuration.

### Playlist Settings

- **Arrangement** — *In podcast order* (groups in the drag-and-drop order you set) or *By release date* (everything merged by date, newest or oldest first)
- **Weekend Only** — Playlist is only rebuilt on Fridays, Saturdays, Sundays, and UK public holidays; on other days it is left untouched
- **Enabled** — Disabled playlists are skipped by the background jobs

### Podcast Attributes

- **Sequential** — Story-based podcasts that must be consumed oldest-to-newest (e.g. serialised true crime). Resolves every assignment's *take from* to oldest unless the row overrides it; in a by-date, newest-first playlist the show keeps the slots it wins but plays oldest-first within them.

Podcasts can belong to multiple playlists simultaneously, with independent rules and ordering per playlist.

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

**Single-user by design.** Registration closes once the first Spotify account signs in, so each deployment serves one person. The `podcasts` table is therefore global (no `user_id`), while `playlists` carries a `user_id` column that predates that decision; nothing relies on it for isolation. Supporting several users would first need a `user_id` on podcasts and owner filtering on every podcast route.

## Screenshots

**Dashboard** — quick stats (total podcasts, playlist assignment progress, playlist status) and one-click sync/update buttons

![Dashboard](docs/screenshots/dashboard-light.png)

**Podcasts** — searchable list with card and table views; inline playlist assignment, sequential toggle, unfollow

![Podcasts](docs/screenshots/podcasts-light.png)

**Playlists** — playlist CRUD with per-playlist defaults and arrangement; a detail page per playlist with drag-and-drop ordering, per-assignment rule overrides, and add/remove

![Playlists](docs/screenshots/playlists-light.png)

**Settings** — Spotify account info, theme selector (light/dark/system/auto)

![Settings](docs/screenshots/settings-light.png)

<details>
<summary>Dark theme</summary>

![Dashboard, dark](docs/screenshots/dashboard-dark.png)
![Podcasts, dark](docs/screenshots/podcasts-dark.png)
![Playlists, dark](docs/screenshots/playlists-dark.png)
![Settings, dark](docs/screenshots/settings-dark.png)

</details>

The images are generated, not hand-captured. With the backend and Vite dev server running:

```bash
cd frontend
npx playwright install chromium       # one-off
npm run screenshots -- --login        # one-off: complete the Spotify login in the window that opens
npm run screenshots                   # writes docs/screenshots/*.png, light and dark
```

The saved session lives in the gitignored `frontend/.screenshots-auth.json`; account details on the Settings page are masked automatically. Rerun `npm run screenshots` whenever the UI changes.

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

- Dev Mode apps are capped at **5 users**, each manually allowlisted in the dashboard. Extended quota is effectively unavailable to hobby apps, so treat this as software for you and your household — not something to open to the public.
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

[PolyForm Noncommercial 1.0.0](LICENSE). You're free to use, modify, and self-host this for personal and other non-commercial purposes. **Commercial use is not permitted** — if you want to use it commercially, get in touch to discuss a separate licence. Contributions are accepted under the same license (see [CONTRIBUTING.md](CONTRIBUTING.md)).
