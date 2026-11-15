import apiClient from './client';
import { jobsApi } from './jobs';
import type {
  AssignmentOverrideUpdate,
  Playlist,
  PlaylistCreate,
  PlaylistUpdate,
  PlaylistListResponse,
  PlaylistPodcast,
  PlaylistPodcastListResponse,
  JobRun,
  PlaylistRunResult,
  PlaylistRunAllResult,
  RunAccepted,
  SpotifyPlaylistOptionListResponse,
} from '../types';

// A manual run that finished without updating anything. failureCode is the
// run's SyncLog failure_code: "credentials_unreadable" means the user has to
// sign in again.
export class RunFailedError extends Error {
  failureCode: string | null;

  constructor(message: string, failureCode: string | null) {
    super(message);
    this.name = 'RunFailedError';
    this.failureCode = failureCode;
  }
}

// Manual runs are started async (issue #242): the server answers 202 with a
// run id at once and the result is polled, so a long rebuild isn't cut off
// by the proxy's 30s timeout. A server that predates async runs ignores the
// header and answers 200 with the result itself.
const RESPOND_ASYNC = { Prefer: 'respond-async' };

function runFailed(run: JobRun): RunFailedError {
  return new RunFailedError(
    run.message || 'Failed to update playlist. Check Run History in Settings for details.',
    run.failure_code
  );
}

async function startRun<T>(url: string): Promise<T | JobRun> {
  const response = await apiClient.post<T | RunAccepted>(url, undefined, {
    headers: RESPOND_ASYNC,
  });
  if (response.status !== 202) return response.data as T;
  return jobsApi.waitForRun((response.data as RunAccepted).run_id);
}

function isJobRun(value: unknown): value is JobRun {
  return typeof value === 'object' && value !== null && 'job_type' in value;
}

export const playlistsApi = {
  // List all managed playlists
  async list(): Promise<Playlist[]> {
    const response = await apiClient.get<PlaylistListResponse>('/playlists');
    return response.data.items;
  },

  // Spotify playlists the user owns, for linking an existing one. Returns the
  // whole response so the picker can say when the server's page cap cut it short.
  async listSpotifyPlaylists(): Promise<SpotifyPlaylistOptionListResponse> {
    const response = await apiClient.get<SpotifyPlaylistOptionListResponse>(
      '/playlists/spotify-playlists'
    );
    return response.data;
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

  // Manually trigger a single playlist update and wait for its result.
  // Resolves for an update, a partial update and a skip, as the synchronous
  // endpoint did; rejects with RunFailedError if nothing was written.
  async run(id: number): Promise<PlaylistRunResult> {
    const outcome = await startRun<PlaylistRunResult>(`/playlists/${id}/run`);
    if (!isJobRun(outcome)) return outcome;
    const result = outcome.results?.[0];
    if (!result || (!result.success && !result.partial)) throw runFailed(outcome);
    return {
      message: outcome.message ?? '',
      playlist_id: result.playlist_id,
      episode_count: result.episode_count,
      skipped: result.skipped || undefined,
      partial: result.partial || undefined,
    };
  },

  // Trigger all playlist updates and wait for the per-playlist results.
  async runAll(): Promise<PlaylistRunAllResult> {
    const outcome = await startRun<PlaylistRunAllResult>('/playlists/run-all');
    if (!isJobRun(outcome)) return outcome;
    if (!outcome.results || outcome.failure_code === 'credentials_unreadable') {
      throw runFailed(outcome);
    }
    return { message: outcome.message ?? '', results: outcome.results };
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
