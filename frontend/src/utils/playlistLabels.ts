import type { AssignmentRule, PickFrom, Playlist } from '../types';

// Human labels for the playlist rule model (docs/design/assignment-rules.md),
// shared by the list table, the dashboard and the detail page so every
// screen describes a rule the same way.

export function episodeLimitLabel(limit: number): string {
  if (limit === 0) return 'All unplayed';
  if (limit === 1) return 'Latest only';
  return `Up to ${limit}`;
}

export function pickFromLabel(pick: PickFrom): string {
  return pick === 'newest' ? 'newest' : 'oldest';
}

// e.g. "Latest only · newest", "Up to 3 · oldest", "All unplayed · oldest".
// The direction is shown even when unlimited because it still sets the order
// the show's episodes are listened to within its group.
export function ruleSummary(limit: number, pick: PickFrom): string {
  return `${episodeLimitLabel(limit)} · ${pickFromLabel(pick)}`;
}

export function dateDirectionLabel(direction: Playlist['date_direction']): string {
  return direction === 'newest_first' ? 'newest first' : 'oldest first';
}

// e.g. "Podcast order" or "By date, newest first".
export function arrangementLabel(
  playlist: Pick<Playlist, 'arrangement' | 'date_direction'>
): string {
  if (playlist.arrangement === 'by_position') return 'Podcast order';
  return `By date, ${dateDirectionLabel(playlist.date_direction)}`;
}

export type RuleSourceLabel = 'custom' | 'sequential' | 'playlist default';

// Where a resolved assignment rule came from, collapsed to one word: "custom"
// wins when either half is overridden, then the sequential hint, else the
// playlist default.
export function ruleSourceLabel(rule: AssignmentRule): RuleSourceLabel {
  if (rule.episode_limit_source === 'override' || rule.pick_from_source === 'override') {
    return 'custom';
  }
  if (rule.pick_from_source === 'sequential') return 'sequential';
  return 'playlist default';
}
