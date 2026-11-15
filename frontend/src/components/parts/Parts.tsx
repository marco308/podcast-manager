import { Tooltip } from 'antd';
import dayjs from 'dayjs';
import type { Playlist } from '../../types';
import { playlistLamp, type LampState } from './lamp';

// The Parts List vocabulary (DESIGN.md): numbered balloons, status lamps
// with their word, and part rows. Styles live in index.css under .pm-*.

export function Balloon({
  n,
  sequential = false,
  unordered = false,
}: {
  n: number;
  sequential?: boolean;
  unordered?: boolean;
}) {
  return (
    <span
      className={`pm-balloon${sequential ? ' is-sequential' : ''}${unordered ? ' is-unordered' : ''}`}
      aria-hidden="true"
    >
      {n}
    </span>
  );
}

export function Lamp({ state, label }: { state: LampState; label?: string }) {
  return (
    <span
      className={`pm-lamp is-${state}`}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}

export function PlaylistStatus({
  playlist,
}: {
  playlist: Pick<Playlist, 'is_enabled' | 'last_run_status' | 'last_run_error' | 'last_run_at'>;
}) {
  const { state, word } = playlistLamp(playlist);
  const when = playlist.last_run_at ? dayjs(playlist.last_run_at).fromNow() : null;
  const reason =
    state === 'partial' || state === 'failed'
      ? [
          state === 'partial'
            ? 'Written from incomplete data'
            : 'Not written; Spotify kept its last version',
          playlist.last_run_error,
          when,
        ]
          .filter(Boolean)
          .join('. ')
      : state === 'off'
        ? 'Turned off: never written to on Spotify'
        : when
          ? `Last run ${when}`
          : undefined;

  const body = (
    <span
      className="pm-status pm-label"
      style={{ color: state === 'partial' || state === 'failed' ? 'var(--ink)' : undefined }}
    >
      <Lamp state={state} />
      {word}
    </span>
  );
  return reason ? <Tooltip title={reason}>{body}</Tooltip> : body;
}

// Why the last build didn't go cleanly, in words, under a playlist's header.
export function RunProblem({
  playlist,
}: {
  playlist: Pick<Playlist, 'is_enabled' | 'last_run_status' | 'last_run_error' | 'last_run_at'>;
}) {
  const status = playlist.last_run_status;
  if (!playlist.is_enabled || (status !== 'partial' && status !== 'failed')) return null;
  const when = playlist.last_run_at ? ` ${dayjs(playlist.last_run_at).fromNow()}` : '';
  const what =
    status === 'partial'
      ? `Written from incomplete data${when}.`
      : `Not written${when}; Spotify kept its last version.`;
  return (
    <p className={`pm-problem is-${status}`}>
      <Lamp state={status} />
      <span>
        {what} {playlist.last_run_error ?? ''}
      </span>
    </p>
  );
}
