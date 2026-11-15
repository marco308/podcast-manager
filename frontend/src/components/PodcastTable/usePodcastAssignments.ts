import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { App } from 'antd';
import type { Podcast } from '../../types';
import {
  podcastKeys,
  useUpdatePodcast,
  useUnfollowPodcast,
  useAddPodcastsToPlaylist,
  useRemovePodcastFromPlaylist,
} from '../../hooks';

interface UsePodcastAssignmentsOptions {
  // Called after a podcast has been archived, restored or unfollowed, so the
  // caller can close whatever it had open for it.
  onLeft: () => void;
}

// The Podcasts page's writes: playlist assignments, the sequential flag,
// archive and unfollow. Owns the optimistic cache updates and the
// per-podcast in-flight tracking that drives every control's spinner.
export function usePodcastAssignments({ onLeft }: UsePodcastAssignmentsOptions) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const updatePodcast = useUpdatePodcast();
  const unfollowPodcast = useUnfollowPodcast();
  const addPodcastsToPlaylist = useAddPodcastsToPlaylist();
  const removePodcastFromPlaylist = useRemovePodcastFromPlaylist();
  // Operations in flight per podcast. A count, not a single id: two rows (or
  // two controls on one row) can be busy at once, and the first to finish
  // must not clear the other's spinner.
  const [inFlight, setInFlight] = useState<ReadonlyMap<number, number>>(() => new Map());

  const isUpdating = (podcastId: number) => (inFlight.get(podcastId) ?? 0) > 0;

  // Run one operation on a podcast with its spinner shown for exactly as
  // long as that operation is in flight.
  const trackUpdate = async (podcastId: number, operation: () => Promise<void>) => {
    setInFlight((prev) => new Map(prev).set(podcastId, (prev.get(podcastId) ?? 0) + 1));
    try {
      await operation();
    } finally {
      setInFlight((prev) => {
        const next = new Map(prev);
        const count = (next.get(podcastId) ?? 0) - 1;
        if (count > 0) {
          next.set(podcastId, count);
        } else {
          next.delete(podcastId);
        }
        return next;
      });
    }
  };

  // Optimistically patch one podcast in every cached list so the table and
  // drawer reflect a change immediately (and a second change diffs against
  // it instead of stale props). In-flight list fetches are cancelled first:
  // one that started before the write would otherwise land after it and put
  // the old value back.
  const patchCachedPodcast = async (podcastId: number, patch: Partial<Podcast>) => {
    await queryClient.cancelQueries({ queryKey: podcastKeys.lists() });
    queryClient.setQueriesData<Podcast[]>({ queryKey: podcastKeys.lists() }, (old) =>
      old?.map((p) => (p.id === podcastId ? { ...p, ...patch } : p))
    );
  };

  // After a failure, re-read the truth rather than restoring a snapshot: with
  // several requests in parallel, some may have succeeded, and an earlier
  // success's refetch may already hold newer data than the snapshot.
  const refetchPodcasts = () => queryClient.invalidateQueries({ queryKey: podcastKeys.lists() });

  const handlePlaylistsChange = (podcast: Podcast, newPlaylistIds: number[]) =>
    trackUpdate(podcast.id, async () => {
      const previousIds = podcast.playlist_ids;
      await patchCachedPodcast(podcast.id, { playlist_ids: newPlaylistIds });
      try {
        const oldIds = new Set(previousIds);
        const newIds = new Set(newPlaylistIds);

        // Find IDs to add and remove
        const toAdd = newPlaylistIds.filter((id) => !oldIds.has(id));
        const toRemove = previousIds.filter((id) => !newIds.has(id));

        // Process additions and removals in parallel
        await Promise.all([
          ...toAdd.map((playlistId) =>
            addPodcastsToPlaylist.mutateAsync({
              playlistId,
              podcastIds: [podcast.id],
            })
          ),
          ...toRemove.map((playlistId) =>
            removePodcastFromPlaylist.mutateAsync({
              playlistId,
              podcastId: podcast.id,
            })
          ),
        ]);

        message.success('Playlist assignments updated');
      } catch {
        void refetchPodcasts();
        message.error('Failed to update playlist assignments');
      }
    });

  const handleSequentialChange = (podcastId: number, checked: boolean) =>
    trackUpdate(podcastId, async () => {
      await patchCachedPodcast(podcastId, { is_sequential: checked });
      try {
        await updatePodcast.mutateAsync({ podcastId, data: { is_sequential: checked } });
        message.success(checked ? 'Marked as sequential' : 'Removed sequential flag');
      } catch {
        void refetchPodcasts();
        message.error('Failed to update');
      }
    });

  // Archive hides the podcast from the app but keeps it followed on Spotify.
  // The backend drops its playlist assignments when archiving.
  const handleArchiveChange = (podcast: Podcast, archived: boolean) =>
    trackUpdate(podcast.id, async () => {
      try {
        await updatePodcast.mutateAsync({
          podcastId: podcast.id,
          data: { is_archived: archived },
        });
        message.success(archived ? `Archived "${podcast.name}"` : `Restored "${podcast.name}"`);
        onLeft();
      } catch {
        message.error(archived ? 'Failed to archive podcast' : 'Failed to restore podcast');
      }
    });

  const handleUnfollow = (podcastId: number, podcastName: string) =>
    trackUpdate(podcastId, async () => {
      try {
        await unfollowPodcast.mutateAsync(podcastId);
        message.success(`Unfollowed "${podcastName}"`);
        onLeft();
      } catch {
        message.error('Failed to unfollow podcast');
      }
    });

  return {
    isUpdating,
    handlePlaylistsChange,
    handleSequentialChange,
    handleArchiveChange,
    handleUnfollow,
  };
}
