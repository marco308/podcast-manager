"""Playlist builder service for generating playlist content based on rules."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.podcast import Podcast, PodcastCategory
from app.models.playlist import Playlist, PlaylistRuleType
from app.models.user import User
from app.services.encryption import get_encryption_service
from app.services.spotify import SpotifyService
from app.utils.holidays import is_weekend_or_holiday

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


class PlaylistBuilder:
    """Service for building and updating playlists based on rules."""

    def __init__(self, db: AsyncSession, user: User) -> None:
        """Initialize playlist builder.

        Args:
            db: Database session.
            user: The user whose playlists to update.
        """
        self._db = db
        self._user = user
        self._encryption = get_encryption_service()
        self._spotify: SpotifyService | None = None

    async def _get_spotify_client(self) -> SpotifyService:
        """Get authenticated Spotify client, refreshing token if needed."""
        if self._spotify:
            return self._spotify

        # Decrypt access token
        access_token = self._encryption.decrypt(self._user.access_token)

        # Check if token is expired and refresh if needed
        if datetime.utcnow() >= self._user.token_expires_at:
            refresh_token = self._encryption.decrypt(self._user.refresh_token)
            spotify = SpotifyService()
            token_data = await spotify.refresh_access_token(refresh_token)

            # Update user tokens
            self._user.access_token = self._encryption.encrypt(token_data["access_token"])
            self._user.refresh_token = self._encryption.encrypt(token_data["refresh_token"])
            self._user.token_expires_at = token_data["expires_at"]
            await self._db.flush()

            access_token = token_data["access_token"]

        self._spotify = SpotifyService(access_token=access_token)
        return self._spotify

    async def _get_podcasts_by_category(
        self, category: PodcastCategory
    ) -> list[Podcast]:
        """Get all podcasts in a category.

        Args:
            category: The podcast category to filter by.

        Returns:
            List of podcasts in the category.
        """
        result = await self._db.execute(
            select(Podcast).where(Podcast.category == category)
        )
        return list(result.scalars().all())

    async def _get_unplayed_episodes(
        self, podcast: Podcast, max_episodes: int = 50
    ) -> list[Episode]:
        """Get unplayed episodes for a podcast.

        Args:
            podcast: The podcast to get episodes for.
            max_episodes: Maximum number of episodes to fetch.

        Returns:
            List of unplayed episodes (excluding subscriber-only/restricted content).
        """
        spotify = await self._get_spotify_client()

        try:
            episodes_data = await spotify.get_show_episodes_all(
                podcast.spotify_id, max_episodes=max_episodes
            )
        except Exception as e:
            logger.error(f"Failed to fetch episodes for {podcast.name}: {e}")
            return []

        # The "shows/{id}/episodes" endpoint does not reliably include a
        # `resume_point` for the current user. Fetch full episode objects
        # via the "episodes" endpoint (in batches) so we can read
        # `resume_point.fully_played` to determine playback status.
        episode_ids = [ep.get("id") for ep in episodes_data if ep and ep.get("id")]

        detailed_episodes: list[dict[str, Any]] = []
        try:
            for i in range(0, len(episode_ids), 50):
                batch = episode_ids[i : i + 50]
                batch_details = await spotify.get_episodes(batch)
                detailed_episodes.extend(batch_details)
        except Exception as e:
            logger.error(f"Failed to fetch detailed episodes for {podcast.name}: {e}")
            return []

        unplayed = []
        for ep in detailed_episodes:
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

            # Check resume_point for playback status (from episodes endpoint)
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

    def _sort_episodes(
        self, episodes: list[Episode], sequential: bool
    ) -> list[Episode]:
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
        self,
        episodes: list[Episode],
        ordering_mode: str,
        podcasts: list[Podcast] | None = None
    ) -> list[Episode]:
        """Apply ordering based on playlist configuration.

        CRITICAL: This method respects the podcast.is_sequential flag.
        Sequential podcasts ALWAYS have their episodes sorted oldest-to-newest,
        regardless of the ordering_mode. Other podcasts can be interleaved between
        sequential podcast episodes.

        Args:
            episodes: Episodes to order
            ordering_mode: Ordering strategy to use
            podcasts: Optional podcast list for PODCAST_ORDER mode

        Returns:
            Ordered list of episodes
        """
        from itertools import groupby

        # Import the enum from models
        from app.models.playlist import PlaylistOrderingMode

        if ordering_mode == PlaylistOrderingMode.CHRONOLOGICAL_ASC.value:
            # Group by podcast to respect is_sequential
            result = []

            # Sort by release date, then group by podcast
            sorted_eps = sorted(episodes, key=lambda e: (e.release_date, e.show_id))
            for show_id, group in groupby(sorted_eps, key=lambda e: e.show_id):
                group_list = list(group)
                # Sequential podcasts: oldest first (already sorted correctly)
                # Non-sequential podcasts: oldest first (already sorted correctly)
                result.extend(group_list)

            return result

        elif ordering_mode == PlaylistOrderingMode.CHRONOLOGICAL_DESC.value:
            # Group by podcast to respect is_sequential
            result = []

            # Sort by release date descending, then group by podcast
            sorted_eps = sorted(episodes, key=lambda e: (e.release_date, e.show_id), reverse=True)
            for show_id, group in groupby(sorted_eps, key=lambda e: e.show_id):
                podcast = next((p for p in (podcasts or []) if p.spotify_id == show_id), None)
                group_list = list(group)

                if podcast and podcast.is_sequential:
                    # Sequential podcasts: MUST be oldest first
                    group_list.sort(key=lambda e: e.release_date)
                # else: non-sequential stays newest first

                result.extend(group_list)

            return result

        elif ordering_mode == PlaylistOrderingMode.PODCAST_ORDER.value and podcasts:
            # Create podcast_id -> (order, is_sequential) mapping
            podcast_order_map = {
                p.spotify_id: (p.playlist_order if p.playlist_order is not None else float('inf'), p.is_sequential)
                for p in podcasts
            }

            # Group episodes by podcast
            episodes_by_order: list[Episode] = []

            # Sort episodes by podcast order first, then by show_id
            sorted_eps = sorted(
                episodes,
                key=lambda e: (
                    podcast_order_map.get(e.show_id, (float('inf'), False))[0],  # playlist_order
                    e.show_id  # group by podcast
                )
            )

            # Within each podcast group, respect is_sequential
            for show_id, group in groupby(sorted_eps, key=lambda e: e.show_id):
                group_list = list(group)
                podcast_info = podcast_order_map.get(show_id, (float('inf'), False))
                is_sequential = podcast_info[1]

                if is_sequential:
                    # Sequential podcasts: MUST be oldest first
                    group_list.sort(key=lambda e: e.release_date)
                else:
                    # Non-sequential podcasts: newest first (default for most playlists)
                    group_list.sort(key=lambda e: e.release_date, reverse=True)

                episodes_by_order.extend(group_list)

            return episodes_by_order

        else:
            # DEFAULT mode - use existing rule_type logic (no reordering)
            return episodes

    async def build_primary_playlist(self, playlist: "Playlist") -> list[str]:
        """Build primary playlist with configurable ordering.

        Args:
            playlist: The playlist configuration

        Returns:
            List of episode URIs for the playlist.
        """
        podcasts = await self._get_podcasts_by_category(PodcastCategory.PRIMARY)
        is_weekend = is_weekend_or_holiday()

        all_episodes: list[Episode] = []

        for podcast in podcasts:
            # Skip weekend-only podcasts on weekdays
            if podcast.is_weekend_only and not is_weekend:
                continue

            episodes = await self._get_unplayed_episodes(podcast)
            sorted_episodes = self._sort_episodes(episodes, podcast.is_sequential)
            all_episodes.extend(sorted_episodes)

        # Apply playlist ordering
        from app.models.playlist import PlaylistOrderingMode
        if playlist.ordering_mode == PlaylistOrderingMode.DEFAULT.value or playlist.ordering_mode == PlaylistOrderingMode.DEFAULT:
            # Default: oldest first for primary
            all_episodes.sort(key=lambda e: e.release_date)
        else:
            all_episodes = self._apply_ordering(all_episodes, str(playlist.ordering_mode.value) if hasattr(playlist.ordering_mode, 'value') else str(playlist.ordering_mode), podcasts)

        return [ep.uri for ep in all_episodes]

    async def build_news_playlist(self, playlist: "Playlist") -> list[str]:
        """Build news playlist with configurable ordering.

        Args:
            playlist: The playlist configuration

        Returns:
            List of episode URIs for the playlist.
        """
        podcasts = await self._get_podcasts_by_category(PodcastCategory.NEWS)
        is_weekend = is_weekend_or_holiday()

        latest_episodes: list[Episode] = []

        for podcast in podcasts:
            # Skip weekend-only podcasts on weekdays
            if podcast.is_weekend_only and not is_weekend:
                continue

            episodes = await self._get_unplayed_episodes(podcast, max_episodes=10)

            if episodes:
                # Sort by release date descending and take the newest
                sorted_eps = self._sort_episodes(episodes, sequential=False)
                latest_episodes.append(sorted_eps[0])

        # Apply playlist ordering
        from app.models.playlist import PlaylistOrderingMode
        if playlist.ordering_mode == PlaylistOrderingMode.DEFAULT.value or playlist.ordering_mode == PlaylistOrderingMode.DEFAULT:
            # Default: newest first for news
            latest_episodes.sort(key=lambda e: e.release_date, reverse=True)
        else:
            latest_episodes = self._apply_ordering(latest_episodes, str(playlist.ordering_mode.value) if hasattr(playlist.ordering_mode, 'value') else str(playlist.ordering_mode), podcasts)

        return [ep.uri for ep in latest_episodes]

    async def build_morning_playlist(self, playlist: "Playlist") -> list[str]:
        """Build morning playlist with configurable ordering.

        Args:
            playlist: The playlist configuration

        Returns:
            List of episode URIs ordered by user preference (playlist_order), then release date.
        """
        podcasts = await self._get_podcasts_by_category(PodcastCategory.NEWS)
        is_weekend = is_weekend_or_holiday()

        latest_episodes: list[Episode] = []

        for podcast in podcasts:
            # Skip weekend-only podcasts on weekdays
            if podcast.is_weekend_only and not is_weekend:
                continue

            episodes = await self._get_unplayed_episodes(podcast, max_episodes=10)

            if episodes:
                # Sort by release date descending and take the newest
                sorted_eps = self._sort_episodes(episodes, sequential=False)
                latest_episodes.append(sorted_eps[0])

        # Apply playlist ordering
        from app.models.playlist import PlaylistOrderingMode
        if playlist.ordering_mode == PlaylistOrderingMode.DEFAULT.value or playlist.ordering_mode == PlaylistOrderingMode.DEFAULT:
            # Backward compatible: use playlist_order (migrated from morning_order)
            latest_episodes = self._apply_ordering(latest_episodes, PlaylistOrderingMode.PODCAST_ORDER.value, podcasts)
        else:
            latest_episodes = self._apply_ordering(latest_episodes, str(playlist.ordering_mode.value) if hasattr(playlist.ordering_mode, 'value') else str(playlist.ordering_mode), podcasts)

        return [ep.uri for ep in latest_episodes]

    async def build_background_playlist(self, playlist: "Playlist") -> list[str]:
        """Build background playlist with configurable ordering.

        Args:
            playlist: The playlist configuration

        Returns:
            List of episode URIs for the playlist.
        """
        podcasts = await self._get_podcasts_by_category(PodcastCategory.BACKGROUND)
        is_weekend = is_weekend_or_holiday()

        all_episodes: list[Episode] = []

        for podcast in podcasts:
            # Skip weekend-only podcasts on weekdays
            if podcast.is_weekend_only and not is_weekend:
                continue

            episodes = await self._get_unplayed_episodes(podcast)
            sorted_episodes = self._sort_episodes(episodes, podcast.is_sequential)
            all_episodes.extend(sorted_episodes)

        # Apply playlist ordering
        from app.models.playlist import PlaylistOrderingMode
        if playlist.ordering_mode == PlaylistOrderingMode.DEFAULT.value or playlist.ordering_mode == PlaylistOrderingMode.DEFAULT:
            # Default: oldest first
            all_episodes.sort(key=lambda e: e.release_date)
        else:
            all_episodes = self._apply_ordering(all_episodes, str(playlist.ordering_mode.value) if hasattr(playlist.ordering_mode, 'value') else str(playlist.ordering_mode), podcasts)

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

        # Build description based on rule type
        descriptions = {
            PlaylistRuleType.PRIMARY: "Primary podcasts - auto-managed by Podcast Manager",
            PlaylistRuleType.NEWS: "News podcasts (latest episodes only) - auto-managed by Podcast Manager",
            PlaylistRuleType.MORNING: "Morning podcasts - auto-managed by Podcast Manager",
            PlaylistRuleType.BACKGROUND: "Background podcasts - auto-managed by Podcast Manager",
        }
        description = descriptions.get(
            playlist.rule_type, "Auto-managed by Podcast Manager"
        )

        spotify_playlist = await spotify.create_playlist(
            user_id=self._user.spotify_id,
            name=playlist.name,
            description=description,
            public=False,
        )

        # Save the Spotify playlist ID
        playlist.spotify_playlist_id = spotify_playlist["id"]
        await self._db.flush()

        logger.info(
            f"Created Spotify playlist '{playlist.name}' with ID {playlist.spotify_playlist_id}"
        )

        return playlist.spotify_playlist_id

    async def update_playlist(self, playlist: Playlist) -> PlaylistUpdateResult:
        """Update a single playlist based on its rule type.

        If the playlist doesn't have a Spotify playlist ID, one will be created.

        Args:
            playlist: The playlist to update.

        Returns:
            Result of the update operation.
        """
        try:
            # Ensure Spotify playlist exists (create if needed)
            spotify_playlist_id = await self._ensure_spotify_playlist(playlist)

            # Build episode list based on rule type
            if playlist.rule_type == PlaylistRuleType.PRIMARY:
                episode_uris = await self.build_primary_playlist(playlist)
            elif playlist.rule_type == PlaylistRuleType.NEWS:
                episode_uris = await self.build_news_playlist(playlist)
            elif playlist.rule_type == PlaylistRuleType.MORNING:
                episode_uris = await self.build_morning_playlist(playlist)
            elif playlist.rule_type == PlaylistRuleType.BACKGROUND:
                episode_uris = await self.build_background_playlist(playlist)
            else:
                return PlaylistUpdateResult(
                    playlist_id=playlist.id,
                    playlist_name=playlist.name,
                    success=False,
                    episode_count=0,
                    error=f"Unknown rule type: {playlist.rule_type}",
                )

            # Update Spotify playlist
            spotify = await self._get_spotify_client()
            await spotify.replace_playlist_items(spotify_playlist_id, episode_uris)

            # Update last_updated_at
            playlist.last_updated_at = datetime.utcnow()
            await self._db.flush()

            logger.info(
                f"Updated playlist '{playlist.name}' with {len(episode_uris)} episodes"
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
            select(Playlist).where(
                (Playlist.user_id == self._user.id) & (Playlist.is_enabled == True)
            )
        )
        playlists = result.scalars().all()

        results = []
        for playlist in playlists:
            result = await self.update_playlist(playlist)
            results.append(result)

        return results
