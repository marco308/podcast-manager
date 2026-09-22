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
  // null = not counted yet; set by a playlist build that read the whole show
  unplayed_episodes: number | null;
  is_sequential: boolean;
  playlist_ids: number[];
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PodcastUpdate {
  is_sequential?: boolean;
}

// Playlist types (see docs/design/assignment-rules.md)

// Which end of a show's unplayed episodes to take from, and the order they
// are listened to.
export type PickFrom = 'newest' | 'oldest';
// How contributions are assembled: grouped per podcast in assignment order,
// or merged across podcasts by release date.
export type Arrangement = 'by_position' | 'by_date';
// Only used when `arrangement` is `by_date`.
export type DateDirection = 'newest_first' | 'oldest_first';
// Where a resolved rule field came from.
export type RuleSource = 'override' | 'sequential' | 'playlist';

// `episode_limit` is 0 for "all unplayed", n >= 1 for "at most n" (max 500).
export const EPISODE_LIMIT_ALL = 0;
export const EPISODE_LIMIT_MAX = 500;

export interface Playlist {
  id: number;
  name: string;
  spotify_playlist_id: string | null;
  is_enabled: boolean;
  is_weekend_only: boolean;
  default_episode_limit: number;
  default_pick_from: PickFrom;
  arrangement: Arrangement;
  date_direction: DateDirection;
  podcast_count: number;
  last_updated_at: string | null;
  created_at: string;
}

export interface PlaylistCreate {
  name: string;
  spotify_playlist_id?: string;
  is_enabled?: boolean;
  is_weekend_only?: boolean;
  default_episode_limit?: number;
  default_pick_from?: PickFrom;
  arrangement?: Arrangement;
  date_direction?: DateDirection;
}

export interface PlaylistUpdate {
  name?: string;
  spotify_playlist_id?: string;
  is_enabled?: boolean;
  is_weekend_only?: boolean;
  default_episode_limit?: number;
  default_pick_from?: PickFrom;
  arrangement?: Arrangement;
  date_direction?: DateDirection;
}

// The rule the next build applies to one assignment, and where each part came from.
export interface AssignmentRule {
  episode_limit: number;
  pick_from: PickFrom;
  episode_limit_source: RuleSource;
  pick_from_source: RuleSource;
}

// The raw per-assignment overrides; null means "inherit".
export interface AssignmentOverride {
  episode_limit: number | null;
  pick_from: PickFrom | null;
}

// Body for PATCH /playlists/{id}/podcasts/{podcast_id}. A field that is
// present and null clears that override; an absent field is left alone.
export interface AssignmentOverrideUpdate {
  episode_limit?: number | null;
  pick_from?: PickFrom | null;
}

export interface PlaylistPodcast {
  id: number;
  spotify_id: string;
  name: string;
  description?: string | null;
  image_url: string | null;
  publisher: string | null;
  total_episodes: number;
  unplayed_episodes: number | null;
  is_sequential: boolean;
  position: number | null;
  rule: AssignmentRule;
  override: AssignmentOverride;
}

// Sync types
export interface SyncResult {
  message: string;
  synced: number;
  new: number;
  removed: number;
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

// Job types
export interface JobSchedule {
  hour: number;
  minute: number;
}

export interface Job {
  id: string;
  name: string;
  next_run: string | null;
  last_run: string | null;
  // Outcome of the run `last_run` refers to (cron jobs only). "failed"
  // covers runs interrupted by a restart, which the backend closes out at
  // startup, so an interrupted run never looks like a good one.
  last_run_status?: 'pending' | 'running' | 'success' | 'failed' | null;
  type: 'cron' | 'interval';
  is_configurable: boolean;
  schedule?: JobSchedule;
  interval_minutes?: number;
}

export interface JobsStatusResponse {
  jobs: Job[];
}

export interface UpdateScheduleResponse {
  message: string;
  next_run: string;
}

// GET /api/health
export interface HealthResponse {
  status: string;
  app: string;
  version: string;
}

// Result of a manual single-playlist run.
// `skipped` is set when a weekend-only playlist was deliberately left
// untouched; `partial` when it was written from incomplete data because some
// podcasts could not be fetched.
export interface PlaylistRunResult {
  message: string;
  playlist_id: number;
  episode_count: number;
  skipped?: boolean;
  partial?: boolean;
}

export interface PlaylistRunAllResult {
  message: string;
  results: {
    playlist_id: number;
    playlist_name: string;
    success: boolean;
    episode_count: number;
    error: string | null;
    skipped: boolean;
    partial: boolean;
  }[];
}
