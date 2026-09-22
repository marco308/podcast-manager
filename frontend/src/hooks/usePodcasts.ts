import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { podcastsApi } from '../api';
import type { PodcastUpdate } from '../types';
import { playlistKeys } from './usePlaylists';

// Query key factory for podcasts
export const podcastKeys = {
  all: ['podcasts'] as const,
  lists: () => [...podcastKeys.all, 'list'] as const,
  list: (includeArchived = false) => [...podcastKeys.lists(), { includeArchived }] as const,
  details: () => [...podcastKeys.all, 'detail'] as const,
  detail: (podcastId: number) => [...podcastKeys.details(), podcastId] as const,
};

// Hook to list podcasts. Archived podcasts are excluded unless asked for, so
// the dashboard counts and assignment selects never see them.
export function usePodcasts({ includeArchived = false }: { includeArchived?: boolean } = {}) {
  return useQuery({
    queryKey: podcastKeys.list(includeArchived),
    queryFn: () => podcastsApi.list({ includeArchived }),
  });
}

// Hook to get a single podcast
export function usePodcast(podcastId: number) {
  return useQuery({
    queryKey: podcastKeys.detail(podcastId),
    queryFn: () => podcastsApi.get(podcastId),
    enabled: !!podcastId,
  });
}

// Hook to update a podcast
export function useUpdatePodcast() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ podcastId, data }: { podcastId: number; data: PodcastUpdate }) =>
      podcastsApi.update(podcastId, data),
    onSuccess: (updatedPodcast) => {
      // Update the specific podcast in cache
      queryClient.setQueryData(podcastKeys.detail(updatedPodcast.id), updatedPodcast);
      // Invalidate list queries to refetch
      queryClient.invalidateQueries({ queryKey: podcastKeys.lists() });
      // Archiving removes the podcast from its playlists, changing
      // podcast_counts and memberships
      queryClient.invalidateQueries({ queryKey: playlistKeys.all });
    },
  });
}

// Hook to sync podcasts from Spotify
export function useSyncPodcasts() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: podcastsApi.sync,
    onSuccess: () => {
      // Invalidate all podcast queries to refetch fresh data
      queryClient.invalidateQueries({ queryKey: podcastKeys.all });
      // A sync never deletes a podcast: shows missing from the Spotify
      // library are flagged `unfollowed_at` and stop contributing episodes,
      // keeping their assignments in case they come back (issue #240). The
      // flag changes what a build produces, so playlist views still need to
      // refetch.
      queryClient.invalidateQueries({ queryKey: playlistKeys.all });
    },
  });
}

// Hook to unfollow a podcast
export function useUnfollowPodcast() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (podcastId: number) => podcastsApi.unfollow(podcastId),
    onSuccess: () => {
      // Invalidate all podcast queries to refetch fresh data
      queryClient.invalidateQueries({ queryKey: podcastKeys.all });
      // Unfollowing deletes the podcast's playlist assignments, changing
      // playlist podcast_counts and memberships
      queryClient.invalidateQueries({ queryKey: playlistKeys.all });
    },
  });
}
