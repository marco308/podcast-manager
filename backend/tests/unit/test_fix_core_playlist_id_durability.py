"""Unit tests: a freshly-created Spotify playlist ID must be durable.

Issue #175. ``_ensure_spotify_playlist`` creates the playlist on Spotify —
a committed external side effect we cannot undo — then records the
returned ID on the local row. It used to only ``flush()``. If the build
that follows failed, the manual-run route raised HTTP 500, ``get_db``
rolled the transaction back, and the app forgot the playlist it had just
created. The next run called ``_ensure_spotify_playlist`` again and made a
*second* Spotify playlist, orphaning the first in the user's library.

The write is therefore committed independently of the build outcome. The
session factory uses ``expire_on_commit=False``, so committing mid-flow
doesn't detach or expire the ORM objects the caller keeps using.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.playlist_builder import PlaylistBuilder


def _make_builder(db: MagicMock) -> PlaylistBuilder:
    user = MagicMock()
    user.id = 1
    token_manager = MagicMock()
    token_manager.get_token = AsyncMock(return_value="token")
    token_manager.force_refresh = AsyncMock(return_value="token")
    return PlaylistBuilder(db, user, token_manager=token_manager)


def _make_db() -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_playlist(spotify_playlist_id: str | None = None) -> MagicMock:
    playlist = MagicMock()
    playlist.id = 3
    playlist.name = "Commute"
    playlist.spotify_playlist_id = spotify_playlist_id
    return playlist


@pytest.mark.asyncio
async def test_new_playlist_id_is_committed_not_just_flushed():
    """The ID write must survive a later rollback of the same session."""
    db = _make_db()
    builder = _make_builder(db)
    playlist = _make_playlist()

    spotify = MagicMock()
    spotify.create_playlist = AsyncMock(return_value={"id": "sp-new"})

    with patch.object(builder, "_get_spotify_client", AsyncMock(return_value=spotify)):
        result = await builder._ensure_spotify_playlist(playlist)

    assert result == "sp-new"
    assert playlist.spotify_playlist_id == "sp-new"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_commit_happens_after_the_spotify_call():
    """Ordering: create remotely, then persist — never the other way round.

    Committing an ID before Spotify confirms it would record a playlist
    that may not exist.
    """
    db = _make_db()
    builder = _make_builder(db)
    playlist = _make_playlist()

    order: list[str] = []

    async def _create(**_kw: object) -> dict:
        order.append("spotify_create")
        return {"id": "sp-new"}

    async def _commit() -> None:
        order.append("db_commit")

    db.commit = AsyncMock(side_effect=_commit)
    spotify = MagicMock()
    spotify.create_playlist = AsyncMock(side_effect=_create)

    with patch.object(builder, "_get_spotify_client", AsyncMock(return_value=spotify)):
        await builder._ensure_spotify_playlist(playlist)

    assert order == ["spotify_create", "db_commit"]


@pytest.mark.asyncio
async def test_existing_playlist_id_short_circuits_without_writing():
    """An already-linked playlist must not create anything or commit."""
    db = _make_db()
    builder = _make_builder(db)
    playlist = _make_playlist("sp-existing")

    spotify = MagicMock()
    spotify.create_playlist = AsyncMock()

    with patch.object(builder, "_get_spotify_client", AsyncMock(return_value=spotify)):
        result = await builder._ensure_spotify_playlist(playlist)

    assert result == "sp-existing"
    spotify.create_playlist.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_id_survives_a_build_failure_later_in_the_same_update():
    """The #175 failure scenario, end to end through ``update_playlist``.

    Spotify creation succeeds, the content build then blows up. The
    result is reported as a failure — but the ID must already be
    committed, so the retry reuses the playlist instead of creating a
    duplicate.
    """
    db = _make_db()
    builder = _make_builder(db)
    playlist = _make_playlist()

    spotify = MagicMock()
    spotify.create_playlist = AsyncMock(return_value={"id": "sp-new"})

    with (
        patch.object(builder, "_get_spotify_client", AsyncMock(return_value=spotify)),
        patch.object(
            builder,
            "_build_playlist_content",
            AsyncMock(side_effect=RuntimeError("spotify 429 storm")),
        ),
    ):
        result = await builder.update_playlist(playlist)

    assert result.success is False
    assert playlist.spotify_playlist_id == "sp-new"
    # The ID commit must have happened before the build failed.
    db.commit.assert_awaited_once()
