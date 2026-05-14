"""Playlist builder service for generating playlist content based on assignments."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.playlist import Playlist, PlaylistOrderingMode
from app.models.playlist_podcast import PlaylistPodcast
from app.models.podcast import Podcast
from app.models.user import User
from app.services.encryption import get_encryption_service
from app.services.spotify import SpotifyService
from app.services.token_manager import TokenManager

logger = logging.getLogger(__name__)


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
        self._encryption = get_encryption_service()
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
        """
        spotify = await self._get_spotify_client()

        try:
            episodes_data = await spotify.get_show_episodes_all(podcast.spotify_id, max_episodes=max_episodes)
        except Exception as e:
            logger.error(f"Failed to fetch episodes for {podcast.name}: {e}")
            return []

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
        from itertools import groupby

        podcasts = [entry.podcast for entry in podcast_entries] if podcast_entries else []

        if ordering_mode == PlaylistOrderingMode.CHRONOLOGICAL_ASC.value:
            # Sort by release date ascending, but respect is_sequential
            sorted_eps = sorted(episodes, key=lambda e: (e.release_date, e.show_id))
            result = []
            for show_id, group in groupby(sorted_eps, key=lambda e: e.show_id):
                podcast = next((p for p in podcasts if p.spotify_id == show_id), None)
                group_list = list(group)
                if podcast and podcast.is_sequential:
                    # Sequential podcasts: always oldest first (already sorted ASC)
                    pass
                # Non-sequential: keep the ASC order as-is
                result.extend(group_list)
            return result

        elif ordering_mode == PlaylistOrderingMode.CHRONOLOGICAL_DESC.value:
            # Sort by release date descending, but respect is_sequential
            sorted_eps = sorted(episodes, key=lambda e: (e.release_date, e.show_id), reverse=True)
            result = []
            for show_id, group in groupby(sorted_eps, key=lambda e: e.show_id):
                podcast = next((p for p in podcasts if p.spotify_id == show_id), None)
                group_list = list(group)
                if podcast and podcast.is_sequential:
                    group_list.sort(key=lambda e: e.release_date)
                result.extend(group_list)
            return result

        elif ordering_mode == PlaylistOrderingMode.PODCAST_ORDER.value and podcast_entries:
            # Order by position from PodcastWithPosition entries
            podcast_order_map = {
                entry.podcast.spotify_id: (
                    entry.position if entry.position is not None else float("inf"),
                    entry.podcast.is_sequential,
                )
                for entry in podcast_entries
            }

            sorted_eps = sorted(
                episodes,
                key=lambda e: (
                    podcast_order_map.get(e.show_id, (float("inf"), False))[0],
                    e.show_id,
                ),
            )

            result = []
            for show_id, group in groupby(sorted_eps, key=lambda e: e.show_id):
                group_list = list(group)
                podcast_info = podcast_order_map.get(show_id, (float("inf"), False))
                is_sequential = podcast_info[1]

                if is_sequential:
                    group_list.sort(key=lambda e: e.release_date)
                else:
                    group_list.sort(key=lambda e: e.release_date, reverse=True)

                result.extend(group_list)

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
        """
        podcast_entries = await self._get_playlist_podcasts(playlist.id)

        if not podcast_entries:
            return []

        all_episodes: list[Episode] = []

        for entry in podcast_entries:
            podcast = entry.podcast
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

        return [ep.uri for ep in all_episodes]

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
        try:
            # Ensure Spotify playlist exists (create if needed)
            spotify_playlist_id = await self._ensure_spotify_playlist(playlist)

            # Build episode list (may take many minutes for users with deep
            # back-catalogues — issue #89).
            episode_uris = await self.build_playlist(playlist)

            # Re-acquire a fresh token immediately before the write. The
            # build step above may have taken long enough that the cached
            # token has expired (or is about to). on_unauthorized handles
            # the residual race where the token expires between this check
            # and Spotify processing the request.
            fresh_token = await self._token_manager.get_token(min_remaining_seconds=300)
            spotify = await self._get_spotify_client()
            spotify._access_token = fresh_token
            await spotify.replace_playlist_items(
                spotify_playlist_id,
                episode_uris,
                on_unauthorized=self._token_manager.force_refresh,
            )

            # Update last_updated_at
            playlist.last_updated_at = datetime.now(UTC)
            await self._db.flush()

            logger.info(f"Updated playlist '{playlist.name}' with {len(episode_uris)} episodes")

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
