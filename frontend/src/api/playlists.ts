import apiClient from './client';
import type { Playlist, PlaylistCreate, PlaylistUpdate } from '../types';

export const playlistsApi = {
  // List all managed playlists
  async list(): Promise<Playlist[]> {
    const response = await apiClient.get<Playlist[]>('/playlists');
    return response.data;
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
};
