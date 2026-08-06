"""Playlist builder service for generating playlist content based on assignments."""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.playlist import Playlist, PlaylistOrderingMode
from app.models.playlist_podcast import PlaylistPodcast
from app.models.podcast import Podcast
from app.models.user import User
from app.services.spotify import SpotifyService
from app.services.token_manager import TokenManager
from app.utils.holidays import is_weekend_or_holiday

logger = logging.getLogger(__name__)


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
class PodcastWithPosition:
    """A podcast together with its position in a playlist."""

    podcast: Podcast
    position: int | None


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

    async def _get_playlist_podcasts(self, playlist_id: int) -> list[PodcastWithPosition]:
        """Get podcasts assigned to a playlist, ordered by position.

        Args:
            playlist_id: The playlist ID to get podcasts for.

        Returns:
            List of PodcastWithPosition ordered by position (nulls last).
        """
        result = await self._db.execute(
            select(Podcast, PlaylistPodcast.position)
            .join(PlaylistPodcast, PlaylistPodcast.podcast_id == Podcast.id)
            .where(PlaylistPodcast.playlist_id == playlist_id)
            .order_by(
                PlaylistPodcast.position.is_(None),  # nulls last
                PlaylistPodcast.position,
                Podcast.name,
            )
        )
        rows = result.all()

        return [PodcastWithPosition(podcast=podcast, position=position) for podcast, position in rows]

    async def _get_unplayed_episodes(self, podcast: Podcast, max_episodes: int = 500) -> list[Episode]:
        """Get unplayed episodes for a podcast.

        Uses the show episodes endpoint directly which includes resume_point
        and is_playable data, avoiding expensive individual episode fetches.

        Args:
            podcast: The podcast to get episodes for.
            max_episodes: Maximum number of episodes to fetch.

        Returns:
            List of unplayed episodes (excluding subscriber-only/restricted content).

        Raises:
            EpisodeFetchError: if Spotify could not be reached or refused the
                request. Callers must distinguish this from an empty result —
                returning ``[]`` here used to let a transient outage clear the
                user's playlist (issue #145).
        """
        spotify = await self._get_spotify_client()

        try:
            episodes_data = await spotify.get_show_episodes_all(podcast.spotify_id, max_episodes=max_episodes)
        except Exception as e:
            logger.error(f"Failed to fetch episodes for {podcast.name}: {e}")
            raise EpisodeFetchError(f"{podcast.name}: {e}") from e

        unplayed = []
        for ep in episodes_data:
            if not ep:
                continue

            # Skip episodes that are not playable (restricted/subscriber-only)
            if not ep.get("is_playable", True):
                logger.debug(f"Skipping non-playable episode: {ep.get('name')}")
                continue

            # Skip episodes with restrictions
            restrictions = ep.get("restrictions", {})
            if restrictions and restrictions.get("reason"):
                logger.debug(f"Skipping restricted episode: {ep.get('name')} - Reason: {restrictions.get('reason')}")
                continue

            # Check resume_point for playback status
            resume_point = ep.get("resume_point") or {}
            fully_played = resume_point.get("fully_played", False)

            if not fully_played:
                unplayed.append(
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
                )

        # Record the real count as a by-product. `sync_podcasts` used to
        # extrapolate this from the newest 50 episodes and store the guess;
        # here we have the actual episode list, so the number is exact —
        # bounded only by `max_episodes` (issue #155).
        if len(episodes_data) < max_episodes:
            podcast.unplayed_episodes = len(unplayed)

        return unplayed

    def _sort_episodes(self, episodes: list[Episode], sequential: bool) -> list[Episode]:
        """Sort episodes based on podcast settings.

        Args:
            episodes: List of episodes to sort.
            sequential: If True, sort oldest to newest. Otherwise, newest to oldest.

        Returns:
            Sorted list of episodes.
        """
        return sorted(
            episodes,
            key=lambda e: e.release_date,
            reverse=not sequential,  # sequential = oldest first, non-sequential = newest first
        )

    @staticmethod
    def _order_chronologically(
        episodes: list[Episode],
        podcasts: list[Podcast],
        *,
        descending: bool,
    ) -> list[Episode]:
        """Sort episodes by release date, keeping sequential shows oldest-first.

        A sequential podcast keeps whichever slots it won in the global
        date ordering — so non-sequential shows still interleave around it —
        but those slots are filled oldest-first rather than following the
        global direction.

        This used to be attempted with :func:`itertools.groupby`, which only
        groups *consecutive* runs. After a global date sort a show's episodes
        are rarely adjacent, so the grouping silently collapsed to size-1
        groups and ``is_sequential`` was ignored in ``chronological_desc``
        (issue #146).

        Args:
            episodes: Episodes to order.
            podcasts: Podcasts assigned to the playlist, for the
                ``is_sequential`` lookup.
            descending: True for newest-first, False for oldest-first.

        Returns:
            Ordered list of episodes.
        """
        ordered = sorted(episodes, key=lambda e: (e.release_date, e.show_id), reverse=descending)

        sequential_shows = {p.spotify_id for p in podcasts if p.is_sequential}
        if not sequential_shows:
            return ordered

        for show_id in sequential_shows:
            slots = [i for i, episode in enumerate(ordered) if episode.show_id == show_id]
            if len(slots) < 2:
                continue
            chronological = sorted((ordered[i] for i in slots), key=lambda e: e.release_date)
            for slot, episode in zip(slots, chronological, strict=True):
                ordered[slot] = episode

        return ordered

    def _apply_ordering(
        self, episodes: list[Episode], ordering_mode: str, podcast_entries: list[PodcastWithPosition] | None = None
    ) -> list[Episode]:
        """Apply ordering based on playlist configuration.

        CRITICAL: This method respects the podcast.is_sequential flag.
        Sequential podcasts ALWAYS have their episodes sorted oldest-to-newest,
        regardless of the ordering_mode. Other podcasts can be interleaved between
        sequential podcast episodes.

        Args:
            episodes: Episodes to order
            ordering_mode: Ordering strategy to use
            podcast_entries: Optional PodcastWithPosition list for PODCAST_ORDER mode

        Returns:
            Ordered list of episodes
        """
        podcasts = [entry.podcast for entry in podcast_entries] if podcast_entries else []

        if ordering_mode == PlaylistOrderingMode.CHRONOLOGICAL_ASC.value:
            return self._order_chronologically(episodes, podcasts, descending=False)

        elif ordering_mode == PlaylistOrderingMode.CHRONOLOGICAL_DESC.value:
            return self._order_chronologically(episodes, podcasts, descending=True)

        elif ordering_mode == PlaylistOrderingMode.PODCAST_ORDER.value and podcast_entries:
            # Order by position from PodcastWithPosition entries
            podcast_order_map = {
                entry.podcast.spotify_id: (
                    entry.position if entry.position is not None else float("inf"),
                    entry.podcast.is_sequential,
                )
                for entry in podcast_entries
            }

            # Group by show explicitly rather than relying on the sort making a
            # show's episodes adjacent — that assumption is what broke the
            # chronological modes (issue #146).
            by_show: dict[str, list[Episode]] = defaultdict(list)
            for episode in episodes:
                by_show[episode.show_id].append(episode)

            result = []
            for show_id in sorted(by_show, key=lambda s: (podcast_order_map.get(s, (float("inf"), False))[0], s)):
                _position, is_sequential = podcast_order_map.get(show_id, (float("inf"), False))
                # Sequential shows play oldest-first; everything else newest-first.
                result.extend(sorted(by_show[show_id], key=lambda e: e.release_date, reverse=not is_sequential))

            return result

        else:
            # DEFAULT mode - no reordering
            return episodes

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
        podcast_entries = await self._get_playlist_podcasts(playlist.id)

        if not podcast_entries:
            return [], []

        all_episodes: list[Episode] = []
        failed_podcasts: list[str] = []

        for entry in podcast_entries:
            podcast = entry.podcast
            try:
                if playlist.episode_mode == "all_unplayed":
                    # Get all unplayed episodes
                    episodes = await self._get_unplayed_episodes(podcast)
                    sorted_episodes = self._sort_episodes(episodes, podcast.is_sequential)
                    all_episodes.extend(sorted_episodes)
                elif playlist.episode_mode == "latest_only":
                    # Get latest unplayed episode only
                    episodes = await self._get_unplayed_episodes(podcast, max_episodes=10)
                    if episodes:
                        sorted_eps = self._sort_episodes(episodes, sequential=False)
                        all_episodes.append(sorted_eps[0])
            except EpisodeFetchError:
                # Keep going: one permanently-broken show (region-locked,
                # delisted) shouldn't block the rest of the playlist forever.
                failed_podcasts.append(podcast.name)

        if failed_podcasts and len(failed_podcasts) == len(podcast_entries):
            # Nothing fetched. An empty write here would wipe the playlist,
            # so refuse it and let the next run retry (issue #145).
            raise PlaylistBuildError(
                f"All {len(podcast_entries)} podcast(s) failed to fetch; "
                f"refusing to overwrite '{playlist.name}' with an empty list"
            )

        if failed_podcasts:
            logger.warning(
                f"Playlist '{playlist.name}' built without {len(failed_podcasts)} "
                f"of {len(podcast_entries)} podcast(s): {', '.join(failed_podcasts)}"
            )

        # Apply ordering
        ordering = (
            str(playlist.ordering_mode.value)
            if hasattr(playlist.ordering_mode, "value")
            else str(playlist.ordering_mode)
        )

        if ordering == PlaylistOrderingMode.DEFAULT.value:
            if playlist.episode_mode == "latest_only":
                # Default for latest_only: newest first
                all_episodes.sort(key=lambda e: e.release_date, reverse=True)
            else:
                # Default for all_unplayed: oldest first
                all_episodes.sort(key=lambda e: e.release_date)
        else:
            all_episodes = self._apply_ordering(all_episodes, ordering, podcast_entries)

        return [ep.uri for ep in all_episodes], failed_podcasts

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

        description = f"{playlist.name} - auto-managed by Podcast Manager"

        spotify_playlist = await spotify.create_playlist(
            name=playlist.name,
            description=description,
            public=False,
            on_unauthorized=self._token_manager.force_refresh,
        )

        # Save the Spotify playlist ID
        playlist.spotify_playlist_id = spotify_playlist["id"]
        await self._db.flush()

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
