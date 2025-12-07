import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { podcastsApi } from '../api';
import type { PodcastCategory, PodcastUpdate } from '../types';

// Query key factory for podcasts
export const podcastKeys = {
  all: ['podcasts'] as const,
  lists: () => [...podcastKeys.all, 'list'] as const,
  list: (category?: PodcastCategory) => [...podcastKeys.lists(), { category }] as const,
  details: () => [...podcastKeys.all, 'detail'] as const,
  detail: (spotifyId: string) => [...podcastKeys.details(), spotifyId] as const,
};

// Hook to list podcasts
export function usePodcasts(category?: PodcastCategory) {
  return useQuery({
    queryKey: podcastKeys.list(category),
    queryFn: () => podcastsApi.list(category),
  });
}

// Hook to get a single podcast
export function usePodcast(spotifyId: string) {
  return useQuery({
    queryKey: podcastKeys.detail(spotifyId),
    queryFn: () => podcastsApi.get(spotifyId),
    enabled: !!spotifyId,
  });
}

// Hook to update a podcast
export function useUpdatePodcast() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ spotifyId, data }: { spotifyId: string; data: PodcastUpdate }) =>
      podcastsApi.update(spotifyId, data),
    onSuccess: (updatedPodcast) => {
      // Update the specific podcast in cache
      queryClient.setQueryData(
        podcastKeys.detail(updatedPodcast.spotify_id),
        updatedPodcast
      );
      // Invalidate list queries to refetch
      queryClient.invalidateQueries({ queryKey: podcastKeys.lists() });
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
    },
  });
}

// Hook to unfollow a podcast
export function useUnfollowPodcast() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (spotifyId: string) => podcastsApi.unfollow(spotifyId),
    onSuccess: () => {
      // Invalidate all podcast queries to refetch fresh data
      queryClient.invalidateQueries({ queryKey: podcastKeys.all });
    },
  });
}
