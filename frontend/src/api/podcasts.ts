import apiClient from './client';
import type { Podcast, PodcastUpdate, SyncResult, PodcastListResponse } from '../types';

export const podcastsApi = {
  // List all podcasts with optional filters
  async list(params?: {
    playlistId?: number;
    unassigned?: boolean;
  }): Promise<Podcast[]> {
    const queryParams: Record<string, string | number | boolean> = {};
    if (params?.playlistId !== undefined) {
      queryParams.playlist_id = params.playlistId;
    }
    if (params?.unassigned !== undefined) {
      queryParams.unassigned = params.unassigned;
    }
    const response = await apiClient.get<PodcastListResponse>('/podcasts', {
      params: queryParams,
    });
    return response.data.items;
  },

  // Get a single podcast by Spotify ID
  async get(spotifyId: string): Promise<Podcast> {
    const response = await apiClient.get<Podcast>(`/podcasts/${spotifyId}`);
    return response.data;
  },

  // Update podcast metadata (is_sequential)
  async update(spotifyId: string, data: PodcastUpdate): Promise<Podcast> {
    const response = await apiClient.patch<Podcast>(`/podcasts/${spotifyId}`, data);
    return response.data;
  },

  // Trigger a sync from Spotify to refresh podcast list
  async sync(): Promise<SyncResult> {
    const response = await apiClient.post<SyncResult>('/podcasts/sync');
    return response.data;
  },

  // Unfollow a podcast from Spotify and remove from database
  async unfollow(spotifyId: string): Promise<{ message: string }> {
    const response = await apiClient.delete<{ message: string }>(`/podcasts/${spotifyId}`);
    return response.data;
  },
};
