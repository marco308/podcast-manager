// User types
export interface User {
  id: number;
  spotify_id: string;
  display_name: string | null;
  email: string | null;
  created_at: string;
  updated_at: string;
}

// Podcast types
export interface Podcast {
  id: number;
  spotify_id: string;
  name: string;
  description: string | null;
  image_url: string | null;
  publisher: string | null;
  total_episodes: number;
  unplayed_episodes: number;
  is_sequential: boolean;
  playlist_ids: number[];
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PodcastUpdate {
  is_sequential?: boolean;
}

// Playlist types
export type EpisodeMode = 'all_unplayed' | 'latest_only';
export type PlaylistOrderingMode =
  | 'default'
  | 'podcast_order'
  | 'chronological_asc'
  | 'chronological_desc';

export interface Playlist {
  id: number;
  name: string;
  spotify_playlist_id: string | null;
  episode_mode: EpisodeMode;
  is_enabled: boolean;
  is_weekend_only: boolean;
  podcast_count: number;
  ordering_mode: PlaylistOrderingMode;
  last_updated_at: string | null;
  created_at: string;
}

export interface PlaylistCreate {
  name: string;
  spotify_playlist_id?: string;
  episode_mode: EpisodeMode;
  is_enabled?: boolean;
  is_weekend_only?: boolean;
  ordering_mode?: PlaylistOrderingMode;
}

export interface PlaylistUpdate {
  name?: string;
  spotify_playlist_id?: string;
  is_enabled?: boolean;
  episode_mode?: EpisodeMode;
  is_weekend_only?: boolean;
  ordering_mode?: PlaylistOrderingMode;
}

export interface PlaylistPodcast {
  id: number;
  spotify_id: string;
  name: string;
  image_url?: string;
  publisher?: string;
  is_sequential: boolean;
  position: number | null;
}

// Sync types
export interface SyncResult {
  message: string;
  synced: number;
  new: number;
}

// Podcast list response
export interface PodcastListResponse {
  items: Podcast[];
  total: number;
}

// Playlist list response
export interface PlaylistListResponse {
  items: Playlist[];
  total: number;
}

// Playlist podcast list response
export interface PlaylistPodcastListResponse {
  items: PlaylistPodcast[];
  total: number;
}

// API Response types
export interface ApiError {
  detail: string;
}
