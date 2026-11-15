import type { Podcast } from '../../types';

export const unfollowDescription = (podcast: Podcast) =>
  podcast.missing_since
    ? `"${podcast.name}" is already gone from your Spotify library. Remove it from this app too?`
    : `Are you sure you want to unfollow "${podcast.name}"? This will remove it from Spotify and delete it from this app.`;

export const archiveDescription = (podcast: Podcast) =>
  `Hide "${podcast.name}" from this app? It stays followed on Spotify` +
  (podcast.playlist_ids.length > 0
    ? ` and will be removed from ${podcast.playlist_ids.length} playlist${podcast.playlist_ids.length === 1 ? '' : 's'}.`
    : '.') +
  ' You can restore it with "Show archived".';
