---
name: spotify-api
description: Spotify Web API constraints for podcast-manager: the Dev Mode batch-endpoint removals, which endpoints remain in use, and how SpotifyService handles 429 Retry-After. Use when touching Spotify sync, episode fetching, or rate limiting.
---

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

**Rate limiting:** Spotify 429s carry a `Retry-After`. `SpotifyService._request_with_retry()` issues up to 3 attempts total (1 + 2 retries); every request goes through it. A sliding-window soft throttle backs off before Spotify has to 429 us; the window is one per process, shared by every `SpotifyService` (issue #314), so a manual sync and a scheduled job pace against each other. A `Retry-After` above the instance's cap is not slept through: the 429 is raised at once as an `httpx.HTTPStatusError` (a build holds `playlist_write_lock` while it waits, and sleeping the cap only earned another 429). The cap is `MAX_RETRY_AFTER_SECONDS` (300s) for jobs and `REQUEST_MAX_RETRY_AFTER_SECONDS` (10s) for anything serving an HTTP request: `routers/_deps.py::spotify_client` and the manual-run `PlaylistBuilder`s pass it as `max_retry_after`.

**Playlist replace:** `replace_playlist_items` is a PUT of the first 100 URIs then POST appends; Spotify has no transactional replace. A failure after the PUT landed (the playlist is now truncated) retries the whole replace once; a failed PUT or a 429 is raised as is.

**`remove_played_episodes` job** (every 30 min, `jobs/cleanup.py`): reads playlist tracks with a `fields` mask that includes `resume_point(fully_played)`, so played episodes are filtered inline with no per-episode fetch. Each run is capped by `CLEANUP_API_CALL_BUDGET` (200 calls, a constant in `scheduler.py`).
