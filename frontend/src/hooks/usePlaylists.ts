import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { playlistsApi } from '../api';
import type { AssignmentOverrideUpdate, PlaylistCreate, PlaylistUpdate } from '../types';
import { podcastKeys } from './usePodcasts';

// Query key factory for playlists
export const playlistKeys = {
  all: ['playlists'] as const,
  lists: () => [...playlistKeys.all, 'list'] as const,
  list: () => [...playlistKeys.lists()] as const,
  detail: (playlistId: number) => [...playlistKeys.all, 'detail', playlistId] as const,
  podcasts: (playlistId: number) => [...playlistKeys.all, 'podcasts', playlistId] as const,
};

// Hook to list playlists
export function usePlaylists() {
  return useQuery({
    queryKey: playlistKeys.list(),
    queryFn: playlistsApi.list,
  });
}

// Hook to get a single playlist
export function usePlaylist(playlistId: number) {
  return useQuery({
    queryKey: playlistKeys.detail(playlistId),
    queryFn: () => playlistsApi.get(playlistId),
    enabled: !!playlistId,
  });
}

// Hook to get podcasts for a playlist
export function usePlaylistPodcasts(playlistId: number) {
  return useQuery({
    queryKey: playlistKeys.podcasts(playlistId),
    queryFn: () => playlistsApi.getPodcasts(playlistId),
    enabled: !!playlistId,
  });
}

// Hook to create a playlist
export function useCreatePlaylist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: PlaylistCreate) => playlistsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: playlistKeys.lists() });
    },
  });
}

// Hook to update a playlist
export function useUpdatePlaylist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: PlaylistUpdate }) =>
      playlistsApi.update(id, data),
    onSuccess: () => {
      // The detail page and the resolved rule on every assignment row both
      // depend on the playlist defaults, so drop everything under the key.
      queryClient.invalidateQueries({ queryKey: playlistKeys.all });
    },
  });
}

// Hook to delete a playlist
export function useDeletePlaylist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => playlistsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: playlistKeys.lists() });
      queryClient.invalidateQueries({ queryKey: podcastKeys.all });
    },
  });
}

// Hook to run a single playlist update
export function useRunPlaylist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => playlistsApi.run(id),
    onSuccess: () => {
      // A run touches last_updated_at (list + detail) and unplayed counts.
      queryClient.invalidateQueries({ queryKey: playlistKeys.all });
    },
  });
}

// Hook to run all playlist updates
export function useRunAllPlaylists() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: playlistsApi.runAll,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: playlistKeys.lists() });
    },
  });
}

// Hook to add podcasts to a playlist
export function useAddPodcastsToPlaylist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ playlistId, podcastIds }: { playlistId: number; podcastIds: number[] }) =>
      playlistsApi.addPodcasts(playlistId, podcastIds),
    onSuccess: (_, { playlistId }) => {
      queryClient.invalidateQueries({ queryKey: playlistKeys.podcasts(playlistId) });
      queryClient.invalidateQueries({ queryKey: playlistKeys.lists() });
      queryClient.invalidateQueries({ queryKey: podcastKeys.all });
    },
  });
}

// Hook to remove a podcast from a playlist
export function useRemovePodcastFromPlaylist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ playlistId, podcastId }: { playlistId: number; podcastId: number }) =>
      playlistsApi.removePodcast(playlistId, podcastId),
    onSuccess: (_, { playlistId }) => {
      queryClient.invalidateQueries({ queryKey: playlistKeys.podcasts(playlistId) });
      queryClient.invalidateQueries({ queryKey: playlistKeys.lists() });
      queryClient.invalidateQueries({ queryKey: podcastKeys.all });
    },
  });
}

// Hook to set or clear the rule overrides on one playlist assignment
export function useUpdatePlaylistPodcast() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      playlistId,
      podcastId,
      data,
    }: {
      playlistId: number;
      podcastId: number;
      data: AssignmentOverrideUpdate;
    }) => playlistsApi.updatePodcastOverride(playlistId, podcastId, data),
    onSuccess: (_, { playlistId }) => {
      queryClient.invalidateQueries({ queryKey: playlistKeys.podcasts(playlistId) });
    },
  });
}

// Hook to reorder podcasts in a playlist
export function useReorderPlaylistPodcasts() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ playlistId, podcastIds }: { playlistId: number; podcastIds: number[] }) =>
      playlistsApi.reorderPodcasts(playlistId, podcastIds),
    onSuccess: (_, { playlistId }) => {
      queryClient.invalidateQueries({ queryKey: playlistKeys.podcasts(playlistId) });
    },
  });
}
