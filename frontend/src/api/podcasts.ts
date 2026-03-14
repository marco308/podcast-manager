import apiClient from './client';
import type {
  Podcast,
  PodcastUpdate,
  PodcastCategory,
  SyncResult,
  PodcastListResponse,
} from '../types';

export const podcastsApi = {
  // List all podcasts with optional category filter
  async list(category?: PodcastCategory): Promise<Podcast[]> {
    const params = category ? { category } : {};
    const response = await apiClient.get<PodcastListResponse>('/podcasts', { params });
    return response.data.items;
  },

  // Get a single podcast by Spotify ID
  async get(spotifyId: string): Promise<Podcast> {
    const response = await apiClient.get<Podcast>(`/podcasts/${spotifyId}`);
    return response.data;
  },

  // Update podcast metadata (category, is_sequential, is_weekend_only)
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
