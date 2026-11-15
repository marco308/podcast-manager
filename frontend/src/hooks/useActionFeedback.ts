import { useState } from 'react';
import { App } from 'antd';
import { getErrorMessage, RunFailedError } from '../api';
import { useAuth } from '../context/AuthContext';
import { syncResultSummary } from '../utils/syncSummary';
import { useSyncPodcasts } from './usePodcasts';
import { useRunAllPlaylists, useRunPlaylist } from './usePlaylists';

// The buttons that trigger a library sync or a playlist rebuild live on more
// than one page. These hooks pair each mutation with the toast that reports
// its result, so every page words the outcome the same way.

// Sync the podcast library from Spotify and report what changed.
export function useSyncPodcastsWithFeedback() {
  const { message } = App.useApp();
  const syncPodcasts = useSyncPodcasts();

  const sync = async () => {
    try {
      const { text, warn } = syncResultSummary(await syncPodcasts.mutateAsync());
      if (warn) {
        message.warning(text);
      } else {
        message.success(text);
      }
    } catch (err: unknown) {
      message.error(`Failed to sync podcasts from Spotify: ${getErrorMessage(err)}`);
    }
  };

  return { sync, isPending: syncPodcasts.isPending };
}

// Reports a failed run. Stored Spotify credentials that can't be read only
// come right with a fresh sign-in, so that case signs out to the login page
// (an async run can't sign the session out itself: its request has already
// answered).
function useReportRunError() {
  const { message } = App.useApp();
  const { logout } = useAuth();

  return (err: unknown) => {
    message.error(getErrorMessage(err));
    if (err instanceof RunFailedError && err.failureCode === 'credentials_unreadable') {
      void logout();
    }
  };
}

// Rebuild every enabled playlist and summarise the per-playlist results.
export function useRunAllPlaylistsWithFeedback() {
  const { message } = App.useApp();
  const runAllPlaylists = useRunAllPlaylists();
  const reportError = useReportRunError();

  const runAll = async () => {
    try {
      const result = await runAllPlaylists.mutateAsync();
      // A 200 only means the batch ran — each playlist carries its own
      // success/skipped/error status, so summarise rather than blanket-success.
      const failed = result.results.filter((r) => !r.success);
      const skipped = result.results.filter((r) => r.success && r.skipped);
      const succeeded = result.results.filter((r) => r.success && !r.skipped);

      let summary = `Updated ${succeeded.length} playlist${succeeded.length === 1 ? '' : 's'}`;
      if (skipped.length > 0) {
        summary += `, ${skipped.length} skipped (disabled)`;
      }

      if (failed.length > 0) {
        message.error(
          `${summary}, ${failed.length} failed: ${failed.map((r) => r.playlist_name).join(', ')}`
        );
      } else if (skipped.length > 0) {
        message.warning(summary);
      } else {
        message.success(summary);
      }
    } catch (err: unknown) {
      reportError(err);
    }
  };

  return { runAll, isPending: runAllPlaylists.isPending };
}

// Rebuild one playlist. Tracks every run in flight, so starting a second
// playlist's run doesn't clear the first one's spinner when it finishes.
export function useRunPlaylistWithFeedback() {
  const { message } = App.useApp();
  const runPlaylist = useRunPlaylist();
  const reportError = useReportRunError();
  const [runningIds, setRunningIds] = useState<ReadonlySet<number>>(() => new Set());

  const run = async (id: number) => {
    setRunningIds((prev) => new Set(prev).add(id));
    try {
      const result = await runPlaylist.mutateAsync(id);
      // A skipped (disabled) playlist and a partial rebuild both come back
      // 200, but neither is a clean success — don't report them as one.
      if (result.skipped || result.partial) {
        message.warning(result.message);
      } else {
        message.success(result.message);
      }
    } catch (err: unknown) {
      reportError(err);
    } finally {
      setRunningIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const isRunning = (id: number) => runningIds.has(id);

  return { run, isRunning };
}
