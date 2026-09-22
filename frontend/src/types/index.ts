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
  // Hidden from the app but still followed on Spotify (issue #247)
  is_archived: boolean;
  playlist_ids: number[];
  last_synced_at: string | null;
  // First sync that found the show gone from the Spotify library (issue
  // #155). While it is set the show contributes no episodes to a build, and
  // the row is deleted once it has been missing for the grace period.
  missing_since: string | null;
  created_at: string;
  updated_at: string;
}

export interface PodcastUpdate {
  is_sequential?: boolean;
  is_archived?: boolean;
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
  spotify_playlist_id?: string | null;
  is_enabled?: boolean;
  is_weekend_only?: boolean;
  default_episode_limit?: number;
  default_pick_from?: PickFrom;
  arrangement?: Arrangement;
  date_direction?: DateDirection;
}

export interface PlaylistUpdate {
  name?: string;
  // Present and null unlinks the Spotify playlist; absent leaves it alone.
  spotify_playlist_id?: string | null;
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
  // Gone from the Spotify library: still assigned, skipped by the next build
  missing_since?: string | null;
  position: number | null;
  rule: AssignmentRule;
  override: AssignmentOverride;
}

// Sync types
export interface SyncResult {
  message: string;
  synced: number;
  new: number;
  // Gone from the Spotify library: counted down over a grace period, then removed
  missing: number;
  removed: number;
  // True when the walk didn't look like a complete snapshot, so nothing was
  // marked or retired. The upserts still happened (issue #240).
  reconcile_skipped: boolean;
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

// A Spotify playlist the user owns, offered as a link target (issue #245).
export interface SpotifyPlaylistOption {
  id: string;
  name: string;
  image_url: string | null;
  item_count: number;
  // The managed playlist already linked to it, if any.
  linked_playlist_id: number | null;
}

export interface SpotifyPlaylistOptionListResponse {
  items: SpotifyPlaylistOption[];
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
  // Outcome of the run `last_run` refers to. Only the jobs that write
  // SyncLog rows (the daily playlist update and the cleanup) report it, so
  // it is absent on the other interval jobs, cron or not. "failed"
  // covers runs interrupted by a restart, which the backend closes out at
  // startup, so an interrupted run never looks like a good one.
  last_run_status?: 'running' | 'success' | 'failed' | null;
  // SyncLog job types that failed on the last run. The daily job runs two
  // steps recorded under one line here, so this names which of them went
  // wrong (issue #240).
  last_run_failed_steps?: string[];
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
