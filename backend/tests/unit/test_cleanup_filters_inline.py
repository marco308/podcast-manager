"""Verify the cleanup job filters played episodes inline from playlist-items.

Issue #89, PR2. Previously cleanup did ``GET /playlists/{id}/items`` then a
follow-up ``GET /episodes/{id}`` per episode to read ``resume_point``.
The ``fields`` mask on the playlist-items call already pulls
``resume_point.fully_played``, so that fan-out was wasted traffic and the
main rate-limit culprit.

This test wires ``SpotifyService`` to an ``httpx.MockTransport`` that:

  - returns 5 items (2 with ``fully_played=True``, 3 with False) from
    ``/playlists/{id}/items``
  - errors loudly if ``/episodes/{id}`` is hit — that would mean the
    refactor failed and we're still doing the per-episode fetch

We assert ``_played_uris_from_items`` selects exactly the two played
URIs, and that the per-episode endpoint was not called.
"""

from __future__ import annotations

import httpx
import pytest

from app.jobs.scheduler import _played_uris_from_items
from app.services.spotify import SpotifyService


def _make_items_payload() -> dict:
    """Five episodes — items 1 and 3 are fully played."""
    return {
        "items": [
            {
                "track": {
                    "uri": "spotify:episode:played1",
                    "resume_point": {"fully_played": True},
                }
            },
            {
                "track": {
                    "uri": "spotify:episode:unplayed1",
                    "resume_point": {"fully_played": False},
                }
            },
            {
                "track": {
                    "uri": "spotify:episode:played2",
                    "resume_point": {"fully_played": True},
                }
            },
            {
                "track": {
                    "uri": "spotify:episode:unplayed2",
                    "resume_point": {"fully_played": False},
                }
            },
            {
                "track": {
                    "uri": "spotify:episode:unplayed3",
                    "resume_point": {"fully_played": False},
                }
            },
        ],
        "next": None,
        "total": 5,
    }


def test_played_uris_from_items_picks_only_fully_played():
    """Helper must pick exactly the two played URIs, in order."""
    played = _played_uris_from_items(_make_items_payload()["items"])
    assert played == ["spotify:episode:played1", "spotify:episode:played2"]


def test_played_uris_from_items_handles_missing_resume_point():
    """A track missing resume_point entirely is treated as not-played."""
    items = [
        {"track": {"uri": "spotify:episode:no_rp"}},
        {"track": {"uri": "spotify:episode:empty_rp", "resume_point": {}}},
        {"track": {"uri": "spotify:episode:none_rp", "resume_point": None}},
    ]
    assert _played_uris_from_items(items) == []


def test_played_uris_from_items_skips_non_episode_tracks():
    """Non-episode tracks (eg songs) and empty/None items don't crash."""
    items = [
        None,
        {"track": None},
        {"track": {"uri": "spotify:track:asong", "resume_point": {"fully_played": True}}},
        {"track": {"uri": "spotify:episode:realone", "resume_point": {"fully_played": True}}},
    ]
    assert _played_uris_from_items(items) == ["spotify:episode:realone"]


@pytest.mark.asyncio
async def test_cleanup_does_not_call_per_episode_endpoint():
    """End-to-end: hit /playlists/{id}/items, never /episodes/{id}.

    Wires SpotifyService at the HTTP boundary and replays the scheduler's
    cleanup inner loop (without the DB/SyncLog shell). If anything
    accidentally falls back to fetching per-episode metadata, the mock
    transport will raise — the test fails loudly rather than silently
    regressing.
    """
    calls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if path.startswith("/v1/episodes/"):
            raise AssertionError(
                f"Cleanup must not call /episodes/{{id}} after PR2; saw {path}"
            )
        if path.endswith("/items") and request.method == "GET":
            return httpx.Response(200, json=_make_items_payload())
        if path.endswith("/items") and request.method == "DELETE":
            return httpx.Response(200, json={"snapshot_id": "snap"})
        return httpx.Response(404, json={"error": f"unexpected {request.method} {path}"})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        spotify = SpotifyService(access_token="tok", client=client)

        # Replay the cleanup inner loop: fetch -> filter -> remove.
        tracks_data = await spotify.get_playlist_tracks(
            "playlist123", limit=50, offset=0, cleanup_mode=True
        )
        played = _played_uris_from_items(tracks_data.get("items", []))
        assert played == ["spotify:episode:played1", "spotify:episode:played2"]

        await spotify.remove_tracks_from_playlist(
            "playlist123", played, cleanup_mode=True
        )

    assert any(p.endswith("/items") for p in calls)
    assert not any(p.startswith("/v1/episodes/") for p in calls)
