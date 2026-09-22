import type { SyncResult } from '../types';

// A sync is a reconciliation, not just an upsert: shows missing from the
// Spotify library are flagged and stop contributing episodes to builds
// (issue #240). Both entry points — the dashboard's quick action and the
// Podcasts page — report it the same way, because a flagged show silently
// changes what the next build produces.
export function syncResultSummary(result: SyncResult): string {
  const extras = [
    result.new > 0 ? `${result.new} new` : null,
    result.unfollowed > 0 ? `${result.unfollowed} no longer followed on Spotify` : null,
    result.refollowed > 0 ? `${result.refollowed} followed again` : null,
  ].filter(Boolean);

  const synced = `${result.synced} podcast${result.synced === 1 ? '' : 's'} synced`;
  return extras.length > 0 ? `${synced} — ${extras.join(', ')}` : synced;
}
