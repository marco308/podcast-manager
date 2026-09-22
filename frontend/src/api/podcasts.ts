import apiClient from './client';
import type { Podcast, PodcastUpdate, SyncResult, PodcastListResponse } from '../types';

// The backend caps `limit` at 100 per request, so a library larger than that
// needs several round-trips. Requesting the maximum keeps that to a minimum.
const PAGE_SIZE = 100;

// Stops a bad `total` or a paging bug from looping forever.
const MAX_PAGES = 100;

export const podcastsApi = {
  // List all podcasts.
  //
  // Pages through the whole result set rather than returning just the first
  // response. The backend defaults to limit=50 and this used to send no
  // pagination params at all, silently capping the UI at 50 podcasts and
  // making the rest unassignable to playlists (issue #151).
  // Archived podcasts are left out unless includeArchived is set.
  async list(params?: { includeArchived?: boolean }): Promise<Podcast[]> {
    const queryParams: Record<string, string | number | boolean> = {};
    if (params?.includeArchived) {
      queryParams.include_archived = true;
    }

    const items: Podcast[] = [];
    let offset = 0;

    for (let page = 0; page < MAX_PAGES; page++) {
      const response = await apiClient.get<PodcastListResponse>('/podcasts', {
        params: { ...queryParams, limit: PAGE_SIZE, offset },
      });

      const batch = response.data.items;
      items.push(...batch);
      offset += batch.length;

      // Stop on a short page (the last one) or once we have everything the
      // server says exists. The empty-batch check guards against a `total`
      // that never converges.
      if (batch.length === 0 || batch.length < PAGE_SIZE || items.length >= response.data.total) {
        break;
      }
    }

    return items;
  },

  // Get a single podcast by ID
  async get(podcastId: number): Promise<Podcast> {
    const response = await apiClient.get<Podcast>(`/podcasts/${podcastId}`);
    return response.data;
  },

  // Update podcast metadata (is_sequential, is_archived)
  async update(podcastId: number, data: PodcastUpdate): Promise<Podcast> {
    const response = await apiClient.patch<Podcast>(`/podcasts/${podcastId}`, data);
    return response.data;
  },

  // Trigger a sync from Spotify to refresh podcast list
  async sync(): Promise<SyncResult> {
    const response = await apiClient.post<SyncResult>('/podcasts/sync');
    return response.data;
  },

  // Unfollow a podcast from Spotify and remove from database
  async unfollow(podcastId: number): Promise<{ message: string }> {
    const response = await apiClient.delete<{ message: string }>(`/podcasts/${podcastId}`);
    return response.data;
  },
};
