# Podcast Manager Project Plan

## Overview

A system to help manage and keep track of podcasts, improving upon Spotify's native organization. The core concept involves categorizing podcasts and automating playlist creation based on specific rules.

## Functional Requirements

### Podcast Categories (Types)

- **Primary**: Most important podcasts.
- **Point in Time (News)**: General news-based podcasts where relevance decays with time. Only the most recent episode is relevant.
- **Background**: Podcasts for filling time or background listening.

### Podcast Attributes

Podcasts can have zero or multiple attributes:

- **Sequential (Oldest to Newest)**: For story-style podcasts that must be consumed in order.
- **Weekend**: Podcasts reserved for weekends (Friday-Sunday) or UK public holidays. These episodes should only be added to playlists on these specific days.

### Playlist Automation Rules

Automated jobs will update specific playlists daily based on the following logic:

- **Primary Playlist**: Contains "Primary" podcasts that haven't been played, ordered from oldest to newest.
- **News Playlist**: Contains only the _most recent_ unplayed episode for each "Point in Time" podcast.
- **Morning Playlist**: A subset of the "News Playlist" designed for morning listening, with a specific play order.
- **Background Playlist**: Contains "Background" podcasts, ordered from oldest to newest, unplayed episodes only.

## Technical Requirements

### Current Context

- Currently using Spotify for podcast management.
- Existing n8n job builds a "morning playlist" using the Spotify API.
- **Decision**: This project will replace the existing n8n job.

### Proposed Architecture

- **Backend**: Python (FastAPI).
- **Database**: SQLite (for storing custom Types, Attributes, and cache).
- **Frontend**: Ant Design (AntD).
- **Authentication**: Spotify OAuth2 (Authorization Code Flow).
- **Deployment**: Docker (Local Server).
  - **Container Strategy**: Separate containers for Backend (FastAPI) and Frontend (AntD/Nginx).
- **Scheduling**: APScheduler (integrated within FastAPI) for playlist updates.

### Key Libraries & Tools

- **Public Holidays**: `holidays` Python package (for UK public holiday logic).

### Security

- **Token Storage**: Spotify refresh tokens will be stored in SQLite using encryption (e.g., Fernet/cryptography).

### Features

1.  **Spotify Integration**:
    - Fetch currently subscribed podcasts.
    - Subscribe/Unsubscribe capabilities.
    - Fetch podcast episodes and playback status.
    - Create and update playlists.
2.  **Metadata Management**:
    - View all subscribed podcasts.
    - Assign custom Types (Primary, News, Background) to podcasts.
    - Assign custom Attributes (Sequential, Weekend) to podcasts.
3.  **Playlist Management**:
    - Define playlists and the logic/rules that generate them.
    - Define update schedules.

## Research Items

- **Rate Limiting**: Research Spotify API rate limits to determine if specific handling logic is needed for daily bulk updates.

## User Stories

1. As a user, I want to view all my subscribed podcasts and their metadata.
2. As a user, I want to assign custom Types and Attributes to my podcasts.
3. As a user, I want to define playlists based on specific rules and have them updated automatically.
4. As a user, I want to authenticate securely with Spotify using OAuth2.
5. As a user, I want to manage my podcast subscriptions directly from the application.
6. As a user, I want to ensure that my playlists are updated daily according to the defined rules.
7. As a user, I want to handle UK public holidays when scheduling weekend podcasts.
8. As a user, I want to ensure that my Spotify tokens are stored securely.
9. As a user, I want to be informed if there are any issues with Spotify API rate limits during playlist updates.
10. As a user, I want to have a simple and intuitive interface for managing my podcasts and playlists.

# references

- [Spotify Web API Documentation](https://developer.spotify.com/documentation/web-api/)
- [Spotify OAuth2 Authorization Code Flow](https://developer.spotify.com/documentation/general/guides/authorization/code-flow/)
