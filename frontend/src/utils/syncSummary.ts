import type { SyncResult } from '../types';

// A sync is a reconciliation, not just an upsert: shows missing from the
// Spotify library are flagged and stop contributing episodes to builds
// (issue #240). Both entry points — the dashboard's quick action and the
// Podcasts page — report it the same way, because a flagged show silently
// changes what the next build produces.
//
// `warn` is set when the backend skipped the unfollow check (Spotify returned
// an empty library, which it can't tell apart from a broken read). The upserts
// landed, so it isn't a failure, but "0 podcasts synced" on its own would read
// as a clean sync of an empty library.
export function syncResultSummary(result: SyncResult): { text: string; warn: boolean } {
  const extras = [
    result.new > 0 ? `${result.new} new` : null,
    result.unfollowed > 0 ? `${result.unfollowed} no longer followed on Spotify` : null,
    result.refollowed > 0 ? `${result.refollowed} followed again` : null,
  ].filter(Boolean);

  const synced = `${result.synced} podcast${result.synced === 1 ? '' : 's'} synced`;
  let text = extras.length > 0 ? `${synced} — ${extras.join(', ')}` : synced;
  if (result.unfollow_check_skipped) {
    text += ' — Spotify returned an empty library, so unfollows were not checked this time';
  }
  return { text, warn: result.unfollow_check_skipped };
}
