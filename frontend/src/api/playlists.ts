import apiClient from './client';
import type {
  AssignmentOverrideUpdate,
  Playlist,
  PlaylistCreate,
  PlaylistUpdate,
  PlaylistListResponse,
  PlaylistPodcast,
  PlaylistPodcastListResponse,
  PlaylistRunResult,
  PlaylistRunAllResult,
  SpotifyPlaylistOption,
  SpotifyPlaylistOptionListResponse,
} from '../types';

export const playlistsApi = {
  // List all managed playlists
  async list(): Promise<Playlist[]> {
    const response = await apiClient.get<PlaylistListResponse>('/playlists');
    return response.data.items;
  },

  // Spotify playlists the user owns, for linking an existing one
  async listSpotifyPlaylists(): Promise<SpotifyPlaylistOption[]> {
    const response = await apiClient.get<SpotifyPlaylistOptionListResponse>(
      '/playlists/spotify-playlists'
    );
    return response.data.items;
  },

  // Get a single managed playlist
  async get(id: number): Promise<Playlist> {
    const response = await apiClient.get<Playlist>(`/playlists/${id}`);
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

  // Delete a playlist mapping. With removeFromSpotify the Spotify playlist is
  // deleted (unfollowed) too; otherwise it is left in place.
  async delete(id: number, removeFromSpotify = false): Promise<void> {
    await apiClient.delete(`/playlists/${id}`, {
      params: removeFromSpotify ? { remove_from_spotify: true } : undefined,
    });
  },

  // Manually trigger a single playlist update
  async run(id: number): Promise<PlaylistRunResult> {
    const response = await apiClient.post<PlaylistRunResult>(`/playlists/${id}/run`);
    return response.data;
  },

  // Trigger all playlist updates
  async runAll(): Promise<PlaylistRunAllResult> {
    const response = await apiClient.post<PlaylistRunAllResult>('/playlists/run-all');
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

  // Set or clear the per-assignment rule overrides for a podcast in a playlist.
  // A field present and null clears that override; an absent field is left
  // alone (JSON serialisation drops undefined but keeps null).
  async updatePodcastOverride(
    playlistId: number,
    podcastId: number,
    data: AssignmentOverrideUpdate
  ): Promise<PlaylistPodcast> {
    const response = await apiClient.patch<PlaylistPodcast>(
      `/playlists/${playlistId}/podcasts/${podcastId}`,
      data
    );
    return response.data;
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
