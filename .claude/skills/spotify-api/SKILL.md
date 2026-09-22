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

**Rate limiting:** Spotify 429s carry a `Retry-After`. `SpotifyService._request_with_retry()` issues up to 3 attempts total (1 + 2 retries); every request goes through it. A per-instance sliding-window soft throttle backs off before Spotify has to 429 us.

**`remove_played_episodes` job** (every 30 min, `jobs/scheduler.py`): reads playlist tracks with a `fields` mask that includes `resume_point(fully_played)`, so played episodes are filtered inline with no per-episode fetch. Each run is capped by `CLEANUP_API_CALL_BUDGET` (200 calls, a constant in `scheduler.py`).
