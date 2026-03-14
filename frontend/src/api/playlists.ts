import apiClient from './client';
import type {
  Playlist,
  PlaylistCreate,
  PlaylistUpdate,
  PlaylistListResponse,
  PlaylistPodcast,
  PlaylistPodcastListResponse,
} from '../types';

export const playlistsApi = {
  // List all managed playlists
  async list(): Promise<Playlist[]> {
    const response = await apiClient.get<PlaylistListResponse>('/playlists');
    return response.data.items;
  },

  // Create a new playlist mapping
  async create(data: PlaylistCreate): Promise<Playlist> {
    const response = await apiClient.post<Playlist>('/playlists', data);
    return response.data;
  },

  // Update a playlist configuration
  async update(id: number, data: PlaylistUpdate): Promise<Playlist> {
    const response = await apiClient.patch<Playlist>(`/playlists/${id}`, data);
    return response.data;
  },

  // Delete a playlist mapping
  async delete(id: number): Promise<void> {
    await apiClient.delete(`/playlists/${id}`);
  },

  // Manually trigger a single playlist update
  async run(id: number): Promise<{ success: boolean; message: string }> {
    const response = await apiClient.post<{ success: boolean; message: string }>(
      `/playlists/${id}/run`
    );
    return response.data;
  },

  // Trigger all playlist updates
  async runAll(): Promise<{ success: boolean; message: string }> {
    const response = await apiClient.post<{ success: boolean; message: string }>(
      '/playlists/run-all'
    );
    return response.data;
  },

  // Get podcasts assigned to a playlist
  async getPodcasts(playlistId: number): Promise<PlaylistPodcast[]> {
    const response = await apiClient.get<PlaylistPodcastListResponse>(
      `/playlists/${playlistId}/podcasts`
    );
    return response.data.items;
  },

  // Add podcasts to a playlist
  async addPodcasts(playlistId: number, podcastIds: number[]): Promise<void> {
    await apiClient.post(`/playlists/${playlistId}/podcasts`, { podcast_ids: podcastIds });
  },

  // Remove a podcast from a playlist
  async removePodcast(playlistId: number, podcastId: number): Promise<void> {
    await apiClient.delete(`/playlists/${playlistId}/podcasts/${podcastId}`);
  },

  // Reorder podcasts in a playlist
  async reorderPodcasts(playlistId: number, podcastIds: number[]): Promise<void> {
    await apiClient.put(`/playlists/${playlistId}/podcasts/reorder`, { podcast_ids: podcastIds });
  },
};
