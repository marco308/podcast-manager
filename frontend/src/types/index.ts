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
export type PodcastCategory = 'primary' | 'news' | 'background' | 'none';

export interface Podcast {
  id: number;
  spotify_id: string;
  name: string;
  description: string | null;
  image_url: string | null;
  publisher: string | null;
  total_episodes: number;
  category: PodcastCategory;
  is_sequential: boolean;
  is_weekend_only: boolean;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PodcastUpdate {
  category?: PodcastCategory;
  is_sequential?: boolean;
  is_weekend_only?: boolean;
}

// Playlist types
export type PlaylistRuleType = 'primary' | 'news' | 'morning' | 'background';

export interface Playlist {
  id: number;
  name: string;
  spotify_playlist_id: string | null;
  rule_type: PlaylistRuleType;
  is_enabled: boolean;
  last_updated_at: string | null;
  created_at: string;
}

export interface PlaylistCreate {
  name: string;
  spotify_playlist_id?: string;
  rule_type: PlaylistRuleType;
  is_enabled?: boolean;
}

export interface PlaylistUpdate {
  name?: string;
  spotify_playlist_id?: string;
  is_enabled?: boolean;
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

// API Response types
export interface ApiError {
  detail: string;
}
