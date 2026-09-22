import type { SyncResult } from '../types';

// A sync reconciles rather than just upserting: shows that have left the
// Spotify library are marked, stop contributing episodes to builds, and are
// deleted after a grace period (issues #155, #240). Both entry points — the
// dashboard's quick action and the Podcasts page — report it the same way,
// because a marked show silently changes what the next build produces.
//
// `warn` is set when the backend didn't trust the walk enough to reconcile
// (a short page, or a total that moved mid-walk). The upserts landed, so it
// isn't a failure, but the counts don't mean what they usually mean.
export function syncResultSummary(result: SyncResult): { text: string; warn: boolean } {
  const extras = [
    result.new > 0 ? `${result.new} new` : null,
    result.missing > 0 ? `${result.missing} no longer subscribed` : null,
    result.removed > 0 ? `${result.removed} removed` : null,
  ].filter(Boolean);

  const synced = `${result.synced} podcast${result.synced === 1 ? '' : 's'} synced`;
  let text = extras.length > 0 ? `${synced} — ${extras.join(', ')}` : synced;
  if (result.reconcile_skipped) {
    text +=
      ' — Spotify returned an incomplete library, so subscriptions were not checked this time';
  }
  return { text, warn: result.reconcile_skipped };
}
