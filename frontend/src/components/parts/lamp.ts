import type { Playlist } from '../../types';

export type LampState = 'ok' | 'partial' | 'failed' | 'off' | 'none';

// One playlist's last-build state as lamp + word, with the client-safe
// reason in a tooltip when it didn't go cleanly.
export function playlistLamp(playlist: Pick<Playlist, 'is_enabled' | 'last_run_status'>): {
  state: LampState;
  word: string;
} {
  if (!playlist.is_enabled) return { state: 'off', word: 'Off' };
  switch (playlist.last_run_status) {
    case 'success':
      return { state: 'ok', word: 'OK' };
    case 'partial':
      return { state: 'partial', word: 'Partial' };
    case 'failed':
      return { state: 'failed', word: 'Failed' };
    default:
      return { state: 'none', word: 'Not run yet' };
  }
}
