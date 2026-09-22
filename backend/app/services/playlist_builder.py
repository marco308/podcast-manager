"""Playlist builder service for generating playlist content based on assignments.

What each show contributes is decided per assignment through
``resolve_rule`` (limit + direction); the playlist decides how the
contributions are assembled (``arrangement`` + ``date_direction``). See
docs/design/assignment-rules.md.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.playlist import Arrangement, DateDirection, PickFrom, Playlist
from app.models.playlist_podcast import PlaylistPodcast
from app.models.podcast import Podcast
from app.models.user import User
from app.services.assignment_rules import ResolvedRule, resolve_rule
from app.services.spotify import SpotifyService
from app.services.token_manager import TokenManager
from app.utils.holidays import is_weekend_or_holiday

logger = logging.getLogger(__name__)

# Per-show fetch cap. Bounds the work for an unlimited rule on a show with a
# huge back-catalogue; a limited rule stops as soon as it has enough.
MAX_EPISODES_PER_SHOW = 500
# Spotify's page size for /shows/{id}/episodes.
PAGE_SIZE = 50


def spotify_playlist_description(name: str) -> str:
    """Description written on the Spotify playlist (on create, and on rename)."""
    return f"{name} - auto-managed by Podcast Manager"


class EpisodeFetchError(Exception):
    """Raised when a podcast's episodes could not be fetched from Spotify.

    Previously a failed fetch was swallowed and reported as "no unplayed
    episodes", which is indistinguishable from a genuinely empty podcast —
    see :class:`PlaylistBuildError` for why that mattered (issue #145).
    """


class PlaylistBuildError(Exception):
    """Raised when a playlist's content could not be built safely.

    ``replace_playlist_items`` is a full replace: writing an empty URI list
    clears the playlist on Spotify. If *every* assigned podcast failed to
    fetch, an empty build is a transient upstream failure rather than a real
    "nothing to play", so we refuse to write it (issue #145).
    """


def parse_release_date(value: str | None) -> date:
    """Turn Spotify's mixed-precision ``release_date`` into a comparable date.

    Spotify reports ``release_date_precision`` of ``year``, ``month`` or
    ``day`` and formats the string accordingly: ``"2024"``, ``"2024-03"`` or
    ``"2024-03-15"``. Comparing those as raw strings puts ``"2024"`` before
    ``"2024-03"`` before any day in March — so an episode with only a year
    sorted ahead of everything else that year, whichever direction the
    playlist was ordered (issue #161). Missing components round down to the
    first month/day; an empty or unparseable value sorts as the earliest
    possible date so it lands at a predictable end of the list.
    """
    if not value:
        return date.min
    parts = value.split("-")
    if len(parts) > 3:
        # Anything beyond YYYY-MM-DD is not a Spotify precision; treat it as
        # unparseable rather than silently truncating to the first three.
        return date.min
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return date(year, month, day)
    except (ValueError, IndexError):
        return date.min


@dataclass
class Episode:
    """Simplified episode data for playlist building."""

    id: str
    uri: str
    name: str
    release_date: str
    duration_ms: int
    fully_played: bool
    show_id: str
    show_name: str

    @property
    def release_date_key(self) -> date:
        """Sort key for ``release_date`` that is safe across precisions."""
        return parse_release_date(self.release_date)


@dataclass
class PlaylistUpdateResult:
    """Result of a playlist update operation."""

    playlist_id: int
    playlist_name: str
    success: bool
    episode_count: int
    error: str | None = None
    # True when the playlist *was* written but from incomplete data — some
    # podcasts failed to fetch. Distinguishes "degraded" from "didn't run",
    # which callers report differently (issue #145).
    partial: bool = False
    # True when the playlist was deliberately left untouched — currently only
    # a weekend-only playlist on a non-qualifying day (issue #150). Not a
    # failure: `success` stays True.
    skipped: bool = False


@dataclass
class AssignmentEntry:
    """A podcast together with its assignment row in a playlist."""

    podcast: Podcast
    assignment: PlaylistPodcast

    @property
    def position(self) -> int | None:
        return self.assignment.position


@dataclass
class ShowContribution:
    """What one assignment contributed to a build: its rule and its episodes."""

    show_id: str
    rule: ResolvedRule
    episodes: list[Episode]


class PlaylistBuilder:
    """Service for building and updating playlists based on direct assignments."""

    def __init__(
        self,
        db: AsyncSession,
        user: User,
        token_manager: TokenManager | None = None,
    ) -> None:
        """Initialize playlist builder.

        Args:
            db: Database session.
            user: The user whose playlists to update.
            token_manager: Per-user token manager. If not supplied, one is
                constructed for ``user.id`` — this preserves backward
                compatibility with existing call sites while letting
                schedulers/routers inject a shared instance (issue #89).
        """
        self._db = db
        self._user = user
        self._token_manager = token_manager if token_manager is not None else TokenManager(user.id)
        self._spotify: SpotifyService | None = None

    async def _get_spotify_client(self) -> SpotifyService:
        """Get authenticated Spotify client with a freshly-checked token.

        The bearer token returned here is suitable for reads. Writes should
        re-acquire a token via ``self._token_manager.get_token(...)`` and
        pass ``on_unauthorized=self._token_manager.force_refresh`` so a 401
        triggered by mid-flight expiry can be recovered.
        """
        access_token = await self._token_manager.get_token(min_remaining_seconds=300)
        if self._spotify is None:
            self._spotify = SpotifyService(access_token=access_token)
        else:
            # Refresh the cached client's token so any subsequent reads
            # (and future shared-client write paths) see the new value.
            self._spotify._access_token = access_token
        return self._spotify

    async def _get_playlist_podcasts(self, playlist_id: int) -> list[AssignmentEntry]:
        """Get podcasts assigned to a playlist with their assignment rows, by position.

        Podcasts marked ``missing_since`` are left out: the show has left the
        user's Spotify library, so it should stop contributing episodes now
        rather than when the row is finally deleted. Marking starts a grace
        period of several days before deletion (issue #155), and for all of it
        the old build kept serving episodes from a show the user had
        unsubscribed from (issue #240). The assignment row is untouched, so a
        show that comes back inside the grace period returns to the playlist
        exactly as it was.

        Returns:
            List of AssignmentEntry ordered by position (nulls last, then name).
        """
        result = await self._db.execute(
            select(Podcast, PlaylistPodcast)
            .join(PlaylistPodcast, PlaylistPodcast.podcast_id == Podcast.id)
            .where((PlaylistPodcast.playlist_id == playlist_id) & (Podcast.missing_since.is_(None)))
            .order_by(
                PlaylistPodcast.position.is_(None),  # nulls last
                PlaylistPodcast.position,
                Podcast.name,
            )
        )
        return [AssignmentEntry(podcast=podcast, assignment=assignment) for podcast, assignment in result.all()]

    @staticmethod
    def _is_unplayed(ep: dict[str, Any] | None) -> bool:
        """True for a playable, unrestricted episode that is not fully played."""
        if not ep:
            return False
        if not ep.get("is_playable", True):
            return False
        restrictions = ep.get("restrictions", {})
        if restrictions and restrictions.get("reason"):
            return False
        resume_point = ep.get("resume_point") or {}
        return not resume_point.get("fully_played", False)

    async def _walk_from_head(
        self, spotify: SpotifyService, show_id: str, need: int | None
    ) -> tuple[list[dict[str, Any]], bool]:
        """Read episodes newest-first from offset 0.

        Stops once ``need`` unplayed episodes have been seen (``None`` means
        read everything up to the cap). Returns ``(raw_episodes, complete)``
        where ``complete`` is True only if the whole catalogue was read.
        """
        items: list[dict[str, Any]] = []
        unplayed = 0
        offset = 0
        while len(items) < MAX_EPISODES_PER_SHOW:
            limit = min(PAGE_SIZE, MAX_EPISODES_PER_SHOW - len(items))
            data = await spotify.get_show_episodes(show_id, limit=limit, offset=offset)
            page = data.get("items", [])
            if not page:
                return items, True
            items.extend(page)
            offset += len(page)
            unplayed += sum(1 for ep in page if self._is_unplayed(ep))
            if need is not None and unplayed >= need:
                return items, not data.get("next")
            if not data.get("next"):
                return items, True
        return items, False

    async def _walk_from_tail(
        self, spotify: SpotifyService, show_id: str, need: int
    ) -> tuple[list[dict[str, Any]], bool]:
        """Read episodes from the *end* of the catalogue until ``need`` unplayed are found.

        Spotify only pages newest-first, so "next unfinished episode of a
        serial" would otherwise mean reading the whole back-catalogue. The
        first page gives ``total``; pages are then read backwards from the
        tail. The result keeps Spotify's newest-first order; ``complete`` is
        True when the head and tail reads met (the whole catalogue was seen).

        The cap applies to the tail candidates only, and the head page is
        only merged in when the reads met. If the walk stops short, the
        unread middle is older than every head episode, so the head must not
        compete for "oldest" — it would be trimmed in ahead of episodes we
        never looked at.
        """
        first = await spotify.get_show_episodes(show_id, limit=PAGE_SIZE, offset=0)
        head: list[dict[str, Any]] = list(first.get("items", []))
        total = first.get("total")
        if not isinstance(total, int) or total <= len(head) or not first.get("next"):
            return head, True

        covered_end = len(head)  # indices [0, covered_end) are in ``head``
        tail: list[dict[str, Any]] = []
        unplayed = 0
        end = total  # exclusive index of the unread region
        while end > covered_end and len(tail) < MAX_EPISODES_PER_SHOW:
            start = max(end - PAGE_SIZE, covered_end)
            data = await spotify.get_show_episodes(show_id, limit=end - start, offset=start)
            page = data.get("items", [])
            if not page:
                break
            tail = page + tail  # keep newest-first overall
            unplayed += sum(1 for ep in page if self._is_unplayed(ep))
            end = start
            if unplayed >= need:
                break

        complete = end <= covered_end
        candidates = head + tail if complete else tail

        # A release between two reads shifts offsets by one; drop any
        # episode seen twice rather than double-adding it.
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for ep in candidates:
            ep_id = ep.get("id") if ep else None
            if not ep_id or ep_id in seen:
                continue
            seen.add(ep_id)
            merged.append(ep)
        return merged, complete

    async def _fetch_unplayed(self, podcast: Podcast, *, need: int | None, from_oldest: bool) -> list[Episode]:
        """Fetch a show's unplayed episodes, reading only as much as the rule needs.

        Args:
            podcast: The podcast to fetch for.
            need: How many unplayed episodes the caller wants, or ``None`` for
                all (up to :data:`MAX_EPISODES_PER_SHOW`).
            from_oldest: Read from the tail of the catalogue (a serial's
                "next unfinished") rather than the head.

        Returns:
            Unplayed, playable episodes in Spotify's newest-first order. The
            caller sorts and trims; this method only bounds the read.

        Raises:
            EpisodeFetchError: if Spotify could not be reached or refused the
                request. Callers must distinguish this from an empty result —
                returning ``[]`` here used to let a transient outage clear the
                user's playlist (issue #145).
        """
        spotify = await self._get_spotify_client()

        try:
            if from_oldest and need is not None:
                raw, complete = await self._walk_from_tail(spotify, podcast.spotify_id, need)
            else:
                raw, complete = await self._walk_from_head(spotify, podcast.spotify_id, need)
        except Exception as e:
            logger.error(f"Failed to fetch episodes for {podcast.name}: {e}")
            raise EpisodeFetchError(f"{podcast.name}: {e}") from e

        unplayed = [
            Episode(
                id=ep["id"],
                uri=ep.get("uri") or f"spotify:episode:{ep['id']}",
                name=ep.get("name", ""),
                release_date=ep.get("release_date", ""),
                duration_ms=ep.get("duration_ms", 0),
                fully_played=False,
                show_id=podcast.spotify_id,
                show_name=podcast.name,
            )
            for ep in raw
            if self._is_unplayed(ep)
        ]

        # Record the real count as a by-product, but only when the walk saw
        # the whole catalogue (issue #155). A limited rule reads a slice and
        # must not overwrite the count with a partial number.
        if complete:
            podcast.unplayed_episodes = len(unplayed)

        return unplayed

    @staticmethod
    def sort_within_show(episodes: list[Episode], pick_from: PickFrom) -> list[Episode]:
        """Order one show's episodes the way its rule says they are listened to."""
        return sorted(episodes, key=lambda e: e.release_date_key, reverse=pick_from == PickFrom.NEWEST)

    @staticmethod
    def assemble(
        contributions: list[ShowContribution],
        arrangement: str,
        date_direction: str,
    ) -> list[Episode]:
        """Assemble per-show contributions into the final playlist order.

        ``by_position`` concatenates the groups as given (assignment order).
        ``by_date`` merges everything by release date in ``date_direction``;
        a show whose rule resolved to ``oldest`` then keeps the slots it won
        in the merge but fills them oldest-first, so a serial is never played
        out of order. ``newest`` is only a preference and follows the
        playlist direction.

        The slot refill is done explicitly rather than by grouping a sorted
        list — a show's episodes are rarely adjacent after a date merge, which
        is what silently broke ``itertools.groupby`` before (issue #146).
        """
        if arrangement == Arrangement.BY_POSITION.value:
            return [episode for group in contributions for episode in group.episodes]

        descending = date_direction == DateDirection.NEWEST_FIRST.value
        ordered = sorted(
            (episode for group in contributions for episode in group.episodes),
            key=lambda e: (e.release_date_key, e.show_id),
            reverse=descending,
        )
        if not descending:
            return ordered

        for group in contributions:
            if group.rule.pick_from != PickFrom.OLDEST:
                continue
            slots = [i for i, episode in enumerate(ordered) if episode.show_id == group.show_id]
            if len(slots) < 2:
                continue
            oldest_first = sorted((ordered[i] for i in slots), key=lambda e: e.release_date_key)
            for slot, episode in zip(slots, oldest_first, strict=True):
                ordered[slot] = episode
        return ordered

    async def build_playlist(self, playlist: Playlist) -> list[str]:
        """Build playlist content based on assigned podcasts and episode mode.

        Args:
            playlist: The playlist configuration.

        Returns:
            List of episode URIs for the playlist.

        Raises:
            PlaylistBuildError: if every assigned podcast failed to fetch.
        """
        uris, _failed = await self._build_playlist_content(playlist)
        return uris

    async def _build_playlist_content(self, playlist: Playlist) -> tuple[list[str], list[str]]:
        """Build playlist content, reporting which podcasts failed to fetch.

        Args:
            playlist: The playlist configuration.

        Returns:
            ``(episode_uris, failed_podcast_names)``. A non-empty failure list
            means the URIs are incomplete — the caller decides whether that is
            safe to write.

        Raises:
            PlaylistBuildError: if the playlist has assigned podcasts but every
                one of them failed to fetch. Writing the resulting empty list
                would clear the playlist on Spotify (issue #145).
        """
        entries = await self._get_playlist_podcasts(playlist.id)

        if not entries:
            return [], []

        contributions: list[ShowContribution] = []
        failed_podcasts: list[str] = []

        for entry in entries:
            podcast = entry.podcast
            rule = resolve_rule(playlist, podcast, entry.assignment)
            try:
                episodes = await self._fetch_unplayed(
                    podcast,
                    need=None if rule.unlimited else rule.episode_limit,
                    from_oldest=rule.pick_from == PickFrom.OLDEST,
                )
            except EpisodeFetchError:
                # Keep going: one permanently-broken show (region-locked,
                # delisted) shouldn't block the rest of the playlist forever.
                failed_podcasts.append(podcast.name)
                continue

            episodes = self.sort_within_show(episodes, rule.pick_from)
            if not rule.unlimited:
                episodes = episodes[: rule.episode_limit]
            contributions.append(ShowContribution(show_id=podcast.spotify_id, rule=rule, episodes=episodes))

        if failed_podcasts and len(failed_podcasts) == len(entries):
            # Nothing fetched. An empty write here would wipe the playlist,
            # so refuse it and let the next run retry (issue #145).
            raise PlaylistBuildError(
                f"All {len(entries)} podcast(s) failed to fetch; refusing to overwrite '{playlist.name}' with an empty list"
            )

        if failed_podcasts:
            logger.warning(
                f"Playlist '{playlist.name}' built without {len(failed_podcasts)} "
                f"of {len(entries)} podcast(s): {', '.join(failed_podcasts)}"
            )

        ordered = self.assemble(contributions, playlist.arrangement, playlist.date_direction)
        return [ep.uri for ep in ordered], failed_podcasts

    async def _ensure_spotify_playlist(self, playlist: Playlist) -> str:
        """Ensure a Spotify playlist exists, creating one if needed.

        Args:
            playlist: The playlist configuration.

        Returns:
            The Spotify playlist ID.
        """
        if playlist.spotify_playlist_id:
            return playlist.spotify_playlist_id

        # Create a new Spotify playlist
        spotify = await self._get_spotify_client()

        spotify_playlist = await spotify.create_playlist(
            name=playlist.name,
            description=spotify_playlist_description(playlist.name),
            public=False,
            on_unauthorized=self._token_manager.force_refresh,
        )

        # Save the Spotify playlist ID — commit, not just flush. The playlist
        # already exists on Spotify (a committed external side effect); if a
        # later build step fails and the session rolls back, a flushed-only
        # write is forgotten and the next run creates a duplicate (issue
        # #175). Mid-flow commit is safe: the session factory uses
        # expire_on_commit=False.
        playlist.spotify_playlist_id = spotify_playlist["id"]
        await self._db.commit()

        logger.info(f"Created Spotify playlist '{playlist.name}' with ID {playlist.spotify_playlist_id}")

        return playlist.spotify_playlist_id

    async def update_playlist(self, playlist: Playlist) -> PlaylistUpdateResult:
        """Update a single playlist based on its assigned podcasts.

        If the playlist doesn't have a Spotify playlist ID, one will be created.

        Args:
            playlist: The playlist to update.

        Returns:
            Result of the update operation.
        """
        # Weekend-only playlists are left completely untouched on a
        # non-qualifying day (issue #150). The gate is here rather than in
        # build_playlist deliberately: an earlier version returned an empty
        # list on weekdays, which — because replace_playlist_items is a full
        # replace — *blanked* the playlist instead of leaving it alone. Skip
        # before any Spotify call so yesterday's contents survive.
        if playlist.is_weekend_only and not is_weekend_or_holiday():
            logger.info(f"Skipping weekend-only playlist '{playlist.name}' — not a weekend or UK public holiday")
            return PlaylistUpdateResult(
                playlist_id=playlist.id,
                playlist_name=playlist.name,
                success=True,
                episode_count=0,
                skipped=True,
            )

        try:
            # Ensure Spotify playlist exists (create if needed)
            spotify_playlist_id = await self._ensure_spotify_playlist(playlist)

            # Build episode list (may take many minutes for users with deep
            # back-catalogues — issue #89). Raises PlaylistBuildError rather
            # than returning an empty list when every fetch failed, so a
            # transient outage can't clear the playlist (issue #145).
            episode_uris, failed_podcasts = await self._build_playlist_content(playlist)

            # Re-acquire a fresh token immediately before the write. The
            # build step above may have taken long enough for the cached
            # token to age out; _get_spotify_client routes through
            # TokenManager.get_token, which refreshes if under the
            # 5-minute threshold. force_refresh handles the residual race
            # where the token expires between this check and Spotify
            # actually processing the request.
            spotify = await self._get_spotify_client()
            await spotify.replace_playlist_items(
                spotify_playlist_id,
                episode_uris,
                on_unauthorized=self._token_manager.force_refresh,
            )

            # Update last_updated_at
            playlist.last_updated_at = datetime.now(UTC)
            await self._db.flush()

            logger.info(f"Updated playlist '{playlist.name}' with {len(episode_uris)} episodes")

            if failed_podcasts:
                # The write went through, but on incomplete data. Report it as
                # a failure so the SyncLog and the UI don't imply the playlist
                # is a faithful rebuild (issue #145).
                return PlaylistUpdateResult(
                    playlist_id=playlist.id,
                    playlist_name=playlist.name,
                    success=False,
                    episode_count=len(episode_uris),
                    error=f"Episodes could not be fetched for: {', '.join(failed_podcasts)}",
                    partial=True,
                )

            return PlaylistUpdateResult(
                playlist_id=playlist.id,
                playlist_name=playlist.name,
                success=True,
                episode_count=len(episode_uris),
            )

        except Exception as e:
            logger.error(f"Failed to update playlist '{playlist.name}': {e}")
            return PlaylistUpdateResult(
                playlist_id=playlist.id,
                playlist_name=playlist.name,
                success=False,
                episode_count=0,
                error=str(e),
            )

    async def update_all_playlists(self) -> list[PlaylistUpdateResult]:
        """Update all enabled playlists.

        Returns:
            List of results for each playlist update.
        """
        result = await self._db.execute(
            select(Playlist).where((Playlist.user_id == self._user.id) & (Playlist.is_enabled == True))
        )
        playlists = result.scalars().all()

        results = []
        for playlist in playlists:
            result = await self.update_playlist(playlist)
            results.append(result)

        return results
