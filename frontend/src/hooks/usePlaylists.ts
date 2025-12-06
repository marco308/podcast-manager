import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { playlistsApi } from '../api';
import type { PlaylistCreate, PlaylistUpdate } from '../types';

// Query key factory for playlists
export const playlistKeys = {
  all: ['playlists'] as const,
  lists: () => [...playlistKeys.all, 'list'] as const,
  list: () => [...playlistKeys.lists()] as const,
};

// Hook to list playlists
export function usePlaylists() {
  return useQuery({
    queryKey: playlistKeys.list(),
    queryFn: playlistsApi.list,
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
      queryClient.invalidateQueries({ queryKey: playlistKeys.lists() });
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
    },
  });
}

// Hook to run a single playlist update
export function useRunPlaylist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => playlistsApi.run(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: playlistKeys.lists() });
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
