# Technical Implementation Plan v2

> A comprehensive technical specification for the Podcast Manager application, derived from the [General Plan](general_plan.md).

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Technology Stack](#2-technology-stack)
3. [Database Design](#3-database-design)
4. [Backend Implementation](#4-backend-implementation)
5. [Frontend Implementation](#5-frontend-implementation)
6. [Spotify Integration](#6-spotify-integration)
7. [Security & Token Management](#7-security--token-management)
8. [Background Job Scheduling](#8-background-job-scheduling)
9. [Docker Deployment](#9-docker-deployment)
10. [Development Phases](#10-development-phases)
11. [API Reference](#11-api-reference)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Network                            │
├─────────────────────┬───────────────────┬───────────────────────┤
│                     │                   │                       │
│  ┌───────────────┐  │  ┌─────────────┐  │  ┌─────────────────┐  │
│  │   Frontend    │  │  │   Backend   │  │  │    SQLite DB    │  │
│  │  (React/Vite) │◄─┼─►│  (FastAPI)  │◄─┼─►│   (Volume)      │  │
│  │   Port 3000   │  │  │  Port 8000  │  │  │                 │  │
│  └───────────────┘  │  └──────┬──────┘  │  └─────────────────┘  │
│                     │         │         │                       │
└─────────────────────┴─────────┼─────────┴───────────────────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │   Spotify Web API     │
                    │   (External Service)  │
                    └───────────────────────┘
```

### Core Components

| Component | Technology                      | Purpose                                            |
| --------- | ------------------------------- | -------------------------------------------------- |
| Frontend  | React + TypeScript + Ant Design | User interface for podcast management              |
| Backend   | Python FastAPI                  | REST API, business logic, job scheduling           |
| Database  | SQLite + SQLAlchemy             | Persistent storage for users, podcasts, playlists  |
| Scheduler | APScheduler                     | Daily automated playlist updates                   |
| External  | Spotify Web API                 | Podcast data, playback status, playlist management |

---

## 2. Technology Stack

### Backend

| Package         | Version | Purpose                                   |
| --------------- | ------- | ----------------------------------------- |
| `fastapi`       | ^0.109  | Web framework with automatic OpenAPI docs |
| `uvicorn`       | ^0.27   | ASGI server                               |
| `sqlalchemy`    | ^2.0    | ORM for database operations               |
| `alembic`       | ^1.13   | Database migrations                       |
| `httpx`         | ^0.26   | Async HTTP client for Spotify API         |
| `apscheduler`   | ^3.10   | Background job scheduling                 |
| `cryptography`  | ^42.0   | Fernet encryption for tokens              |
| `holidays`      | ^0.40   | UK public holiday detection               |
| `pydantic`      | ^2.6    | Data validation and settings management   |
| `python-dotenv` | ^1.0    | Environment variable management           |

### Frontend

| Package                 | Version | Purpose                   |
| ----------------------- | ------- | ------------------------- |
| `react`                 | ^18     | UI framework              |
| `typescript`            | ^5      | Type safety               |
| `vite`                  | ^5      | Build tool and dev server |
| `antd`                  | ^5      | UI component library      |
| `@tanstack/react-query` | ^5      | Server state management   |
| `react-router-dom`      | ^6      | Client-side routing       |
| `axios`                 | ^1      | HTTP client               |

---

## 3. Database Design

### Entity Relationship Diagram

```
┌──────────────┐       ┌──────────────────┐       ┌───────────────┐
│    users     │       │     podcasts     │       │   playlists   │
├──────────────┤       ├──────────────────┤       ├───────────────┤
│ id (PK)      │       │ id (PK)          │       │ id (PK)       │
│ spotify_id   │       │ spotify_id       │       │ name          │
│ display_name │       │ name             │       │ spotify_id    │
│ access_token │       │ description      │       │ rule_type     │
│ refresh_token│       │ image_url        │       │ is_enabled    │
│ token_expires│       │ publisher        │       │ last_updated  │
│ created_at   │       │ total_episodes   │       └───────────────┘
│ updated_at   │       │ category         │
└──────────────┘       │ is_sequential    │
                       │ is_weekend_only  │
                       │ last_synced_at   │
                       └──────────────────┘
```

### Table Definitions

#### `users`

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    email VARCHAR(255),
    access_token TEXT NOT NULL,           -- Encrypted
    refresh_token TEXT NOT NULL,          -- Encrypted
    token_expires_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### `podcasts`

```sql
CREATE TABLE podcasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    description TEXT,
    image_url VARCHAR(500),
    publisher VARCHAR(255),
    total_episodes INTEGER DEFAULT 0,

    -- Custom categorization fields
    category VARCHAR(20) DEFAULT 'none'
        CHECK (category IN ('primary', 'news', 'background', 'none')),
    is_sequential BOOLEAN DEFAULT FALSE,
    is_weekend_only BOOLEAN DEFAULT FALSE,

    last_synced_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_podcasts_category ON podcasts(category);
CREATE INDEX idx_podcasts_spotify_id ON podcasts(spotify_id);
```

#### `playlists`

```sql
CREATE TABLE playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    spotify_playlist_id VARCHAR(255),
    rule_type VARCHAR(20) NOT NULL
        CHECK (rule_type IN ('primary', 'news', 'morning', 'background')),
    is_enabled BOOLEAN DEFAULT TRUE,
    last_updated_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### `sync_logs` (Optional - for debugging/monitoring)

```sql
CREATE TABLE sync_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    details TEXT,
    started_at DATETIME,
    completed_at DATETIME
);
```

---

## 4. Backend Implementation

### Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── config.py               # Settings and environment variables
│   ├── database.py             # SQLAlchemy engine and session
│   │
│   ├── models/                 # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── podcast.py
│   │   └── playlist.py
│   │
│   ├── schemas/                # Pydantic schemas for validation
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── podcast.py
│   │   └── playlist.py
│   │
│   ├── routers/                # API route handlers
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── podcasts.py
│   │   └── playlists.py
│   │
│   ├── services/               # Business logic
│   │   ├── __init__.py
│   │   ├── spotify.py          # Spotify API client
│   │   ├── encryption.py       # Token encryption/decryption
│   │   ├── sync.py             # Podcast sync logic
│   │   └── playlist_builder.py # Playlist generation logic
│   │
│   ├── jobs/                   # Background jobs
│   │   ├── __init__.py
│   │   ├── scheduler.py        # APScheduler setup
│   │   ├── token_refresh.py
│   │   └── playlist_update.py
│   │
│   └── utils/                  # Helper functions
│       ├── __init__.py
│       └── holidays.py         # UK holiday logic
│
├── alembic/                    # Database migrations
│   ├── versions/
│   └── env.py
│
├── alembic.ini
├── requirements.txt
├── Dockerfile
└── .env.example
```

### Configuration (`app/config.py`)

```python
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Podcast Manager"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "sqlite:///./podcast_manager.db"

    # Spotify OAuth
    SPOTIFY_CLIENT_ID: str
    SPOTIFY_CLIENT_SECRET: str
    SPOTIFY_REDIRECT_URI: str = "http://localhost:8000/api/auth/callback"
    SPOTIFY_SCOPES: str = "user-read-playback-position user-library-read playlist-modify-public playlist-modify-private"

    # Security
    ENCRYPTION_KEY: str  # Fernet key for token encryption
    SECRET_KEY: str      # JWT/session secret

    # Scheduler
    PLAYLIST_UPDATE_HOUR: int = 4  # 4:00 AM
    PLAYLIST_UPDATE_MINUTE: int = 0

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

---

## 5. Frontend Implementation

### Project Structure

```
frontend/
├── public/
│   └── favicon.ico
├── src/
│   ├── main.tsx                # React entry point
│   ├── App.tsx                 # Root component with routing
│   ├── App.css
│   ├── index.css
│   │
│   ├── api/                    # API client functions
│   │   ├── client.ts           # Axios instance
│   │   ├── auth.ts
│   │   ├── podcasts.ts
│   │   └── playlists.ts
│   │
│   ├── components/             # Reusable components
│   │   ├── Layout/
│   │   │   ├── Header.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   └── MainLayout.tsx
│   │   ├── PodcastTable/
│   │   │   ├── PodcastTable.tsx
│   │   │   ├── CategorySelect.tsx
│   │   │   └── AttributeTags.tsx
│   │   └── common/
│   │       ├── LoadingSpinner.tsx
│   │       └── ErrorBoundary.tsx
│   │
│   ├── pages/                  # Route pages
│   │   ├── Login.tsx
│   │   ├── Dashboard.tsx
│   │   ├── Podcasts.tsx
│   │   ├── Playlists.tsx
│   │   └── Settings.tsx
│   │
│   ├── hooks/                  # Custom React hooks
│   │   ├── useAuth.ts
│   │   ├── usePodcasts.ts
│   │   └── usePlaylists.ts
│   │
│   ├── context/                # React Context providers
│   │   └── AuthContext.tsx
│   │
│   ├── types/                  # TypeScript type definitions
│   │   ├── podcast.ts
│   │   ├── playlist.ts
│   │   └── user.ts
│   │
│   └── utils/                  # Utility functions
│       └── formatters.ts
│
├── index.html
├── vite.config.ts
├── tsconfig.json
├── package.json
└── Dockerfile
```

### Key UI Components

#### Podcast Manager Table

The primary interface for categorizing podcasts:

| Column       | Type     | Description                               |
| ------------ | -------- | ----------------------------------------- |
| Cover        | Image    | Podcast artwork thumbnail                 |
| Name         | Text     | Podcast title (clickable for details)     |
| Publisher    | Text     | Show publisher                            |
| Episodes     | Number   | Total episode count                       |
| Category     | Select   | Dropdown: Primary, News, Background, None |
| Sequential   | Checkbox | Story-based ordering toggle               |
| Weekend Only | Checkbox | Weekend/holiday restriction toggle        |
| Last Synced  | DateTime | Last Spotify sync timestamp               |

#### Dashboard Cards

- **Sync Status**: Last sync time, podcast count, "Sync Now" button
- **Playlist Status**: Grid showing each managed playlist's last update
- **Quick Actions**: Manual trigger buttons for each playlist rule

---

## 6. Spotify Integration

### OAuth2 Authorization Code Flow

```
┌─────────┐                                              ┌─────────┐
│  User   │                                              │ Spotify │
└────┬────┘                                              └────┬────┘
     │                                                        │
     │  1. Click "Login with Spotify"                         │
     │  ──────────────────────────────►                       │
     │                                                        │
     │  2. Redirect to Spotify Auth                           │
     │  ◄──────────────────────────────                       │
     │                                                        │
     │  3. User grants permissions                            │
     │  ──────────────────────────────►                       │
     │                                                        │
     │  4. Redirect to callback with code                     │
     │  ◄──────────────────────────────                       │
     │                                                        │
     │  5. Exchange code for tokens                           │
     │  ──────────────────────────────►                       │
     │                                                        │
     │  6. Return access_token + refresh_token                │
     │  ◄──────────────────────────────                       │
     │                                                        │
```

### Required Spotify Scopes

| Scope                         | Purpose                             |
| ----------------------------- | ----------------------------------- |
| `user-library-read`           | Access subscribed podcasts          |
| `user-read-playback-position` | Determine played/unplayed episodes  |
| `playlist-modify-public`      | Create and update public playlists  |
| `playlist-modify-private`     | Create and update private playlists |

### Key Spotify Endpoints

| Endpoint                     | Method | Purpose                          |
| ---------------------------- | ------ | -------------------------------- |
| `/me/shows`                  | GET    | Fetch user's subscribed podcasts |
| `/shows/{id}/episodes`       | GET    | Fetch episodes for a podcast     |
| `/me/player/recently-played` | GET    | Check playback history           |
| `/playlists/{id}/tracks`     | PUT    | Replace playlist tracks          |
| `/playlists`                 | POST   | Create new playlist              |

### Rate Limiting Considerations

- Spotify API rate limit: ~180 requests per minute
- Strategy: Implement exponential backoff and batch requests where possible
- Episode fetching: Limit to 50 per request, paginate as needed

---

## 7. Security & Token Management

### Token Encryption

All Spotify tokens are encrypted at rest using Fernet symmetric encryption:

```python
from cryptography.fernet import Fernet
import os

class TokenEncryption:
    def __init__(self):
        key = os.getenv("ENCRYPTION_KEY")
        self.cipher = Fernet(key.encode())

    def encrypt(self, token: str) -> str:
        return self.cipher.encrypt(token.encode()).decode()

    def decrypt(self, encrypted_token: str) -> str:
        return self.cipher.decrypt(encrypted_token.encode()).decode()
```

### Environment Variables

```bash
# .env.example
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://localhost:8000/api/auth/callback

# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=your_fernet_key

SECRET_KEY=your_random_secret_key

DATABASE_URL=sqlite:///./podcast_manager.db
```

### Security Best Practices

1. **Never log tokens** - Mask in all log outputs
2. **HTTPS in production** - Enforce TLS for all API communications
3. **Token refresh** - Proactively refresh before expiration (1 hour)
4. **Environment isolation** - Use Docker secrets or vault in production

---

## 8. Background Job Scheduling

### APScheduler Configuration

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

# Daily playlist update at 4:00 AM
scheduler.add_job(
    update_all_playlists,
    CronTrigger(hour=4, minute=0),
    id="daily_playlist_update",
    name="Daily Playlist Update",
    replace_existing=True
)

# Token refresh every 45 minutes
scheduler.add_job(
    refresh_spotify_tokens,
    "interval",
    minutes=45,
    id="token_refresh",
    name="Spotify Token Refresh"
)
```

### Playlist Update Logic

```
┌─────────────────────────────────────────────────────────────────┐
│                    Daily Playlist Update Job                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Check if today is weekend (Fri/Sat/Sun) or UK holiday       │
│     │                                                            │
│  2. For each playlist rule (primary, news, background):         │
│     │                                                            │
│     ├─► Fetch podcasts matching the category                    │
│     │                                                            │
│     ├─► For each podcast:                                       │
│     │   ├─► If weekend_only AND NOT (weekend OR holiday): SKIP  │
│     │   ├─► Fetch unplayed episodes from Spotify                │
│     │   └─► Apply sorting (oldest→newest for sequential)        │
│     │                                                            │
│     ├─► NEWS special case: Only keep latest episode per show    │
│     │                                                            │
│     └─► Push final track list to Spotify playlist               │
│                                                                  │
│  3. Log results and update last_updated_at                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### UK Holiday Detection

```python
import holidays
from datetime import date

def is_weekend_or_holiday(check_date: date = None) -> bool:
    if check_date is None:
        check_date = date.today()

    # Check if Friday (4), Saturday (5), or Sunday (6)
    if check_date.weekday() >= 4:
        return True

    # Check UK public holidays
    uk_holidays = holidays.UK(years=check_date.year)
    return check_date in uk_holidays
```

---

## 9. Docker Deployment

### docker-compose.yml

```yaml
version: "3.8"

services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: podcast-manager-api
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data # SQLite database persistence
    environment:
      - DATABASE_URL=sqlite:///./data/podcast_manager.db
    env_file:
      - .env
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: podcast-manager-web
    ports:
      - "3000:80"
    depends_on:
      - backend
    restart: unless-stopped
```

### Backend Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Frontend Dockerfile

```dockerfile
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

---

## 10. Development Phases

### Phase 1: Foundation & Authentication (Week 1-2)

**Objectives:**

- [ ] Initialize FastAPI project with proper structure
- [ ] Configure SQLite + SQLAlchemy with initial models
- [ ] Set up Alembic migrations
- [ ] Implement Spotify OAuth2 flow (login, callback, token storage)
- [ ] Implement Fernet token encryption/decryption
- [ ] Create basic health check and auth endpoints

**Deliverables:**

- Working OAuth flow with encrypted token storage
- Database with users table populated on login

---

### Phase 2: Podcast Sync & Management (Week 3-4)

**Objectives:**

- [ ] Create Spotify API client service
- [ ] Implement "Sync Subscriptions" job (fetch → save)
- [ ] Build CRUD endpoints for podcasts
- [ ] Build React frontend scaffold with Ant Design
- [ ] Create Podcast Manager table with editable fields
- [ ] Implement category/attribute updates

**Deliverables:**

- Full podcast list synced from Spotify
- UI for viewing and categorizing podcasts

---

### Phase 3: Playlist Logic & Automation (Week 5-6)

**Objectives:**

- [ ] Implement episode fetching with playback status
- [ ] Build playlist generation logic for each rule type
- [ ] Implement UK holiday detection
- [ ] Set up APScheduler with daily job
- [ ] Create playlist mapping configuration
- [ ] Build manual trigger endpoints

**Deliverables:**

- Automated daily playlist updates
- Manual trigger buttons in UI
- Weekend/holiday logic working

---

### Phase 4: Deployment & Polish (Week 7-8)

**Objectives:**

- [ ] Create Dockerfiles for both services
- [ ] Set up docker-compose with volume persistence
- [ ] Add error handling and logging throughout
- [ ] UI polish (loading states, error messages, notifications)
- [ ] Write basic documentation
- [ ] Test full workflow end-to-end

**Deliverables:**

- Production-ready Docker deployment
- Complete, polished application

---

## 11. API Reference

### Authentication

| Method | Endpoint             | Description                 |
| ------ | -------------------- | --------------------------- |
| GET    | `/api/auth/login`    | Initiate Spotify OAuth flow |
| GET    | `/api/auth/callback` | OAuth callback handler      |
| GET    | `/api/auth/me`       | Get current user info       |
| POST   | `/api/auth/logout`   | Clear session               |

### Podcasts

| Method | Endpoint                     | Description                                      |
| ------ | ---------------------------- | ------------------------------------------------ |
| GET    | `/api/podcasts`              | List all podcasts (supports `?category=` filter) |
| GET    | `/api/podcasts/{spotify_id}` | Get single podcast details                       |
| PATCH  | `/api/podcasts/{spotify_id}` | Update podcast metadata                          |
| POST   | `/api/podcasts/sync`         | Trigger manual sync from Spotify                 |

**PATCH Request Body:**

```json
{
  "category": "primary",
  "is_sequential": true,
  "is_weekend_only": false
}
```

### Playlists

| Method | Endpoint                  | Description                      |
| ------ | ------------------------- | -------------------------------- |
| GET    | `/api/playlists`          | List managed playlists           |
| POST   | `/api/playlists`          | Create new playlist mapping      |
| PATCH  | `/api/playlists/{id}`     | Update playlist configuration    |
| POST   | `/api/playlists/{id}/run` | Manually trigger playlist update |
| POST   | `/api/playlists/run-all`  | Trigger all playlist updates     |

### System

| Method | Endpoint           | Description                |
| ------ | ------------------ | -------------------------- |
| GET    | `/api/health`      | Health check               |
| GET    | `/api/jobs/status` | Get scheduler job statuses |

---

## Appendix

### Generating Encryption Key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Local Development Setup

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your values
alembic upgrade head
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

### Useful Links

- [Spotify Web API Documentation](https://developer.spotify.com/documentation/web-api/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Ant Design Components](https://ant.design/components/overview)
- [APScheduler Documentation](https://apscheduler.readthedocs.io/)
