import { Button, Skeleton } from 'antd';
import { Link } from 'react-router';
import { usePlaylistPodcasts, useRunPlaylistWithFeedback } from '../../hooks';
import type { Playlist } from '../../types';
import { arrangementLabel } from '../../utils/playlistLabels';
import { PlaylistStatus, RunProblem } from './Parts';
import { PartRow } from './PartRow';

// One managed playlist drawn as an assembly: its shows are numbered parts,
// each with the rule the next rebuild will apply as its spec.
export function PlaylistAssembly({ playlist }: { playlist: Playlist }) {
  const { data, isLoading, isError } = usePlaylistPodcasts(playlist.id);
  const { run, isRunning } = useRunPlaylistWithFeedback();
  const parts = data ?? [];

  return (
    <section className="pm-sheet pm-draw" aria-labelledby={`asm-${playlist.id}`}>
      <header className="pm-sheet-head">
        <div style={{ minWidth: 0 }}>
          <Link to={`/playlists/${playlist.id}`}>
            <h2 id={`asm-${playlist.id}`} className="pm-title">
              {playlist.name}
            </h2>
          </Link>
          <div className="pm-label" style={{ marginTop: 6 }}>
            {arrangementLabel(playlist)}
            {playlist.kind === 'sleep' ? ' · Sleep' : ''}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flex: 'none' }}>
          <PlaylistStatus playlist={playlist} />
          <Button
            size="small"
            onClick={() => run(playlist.id)}
            loading={isRunning(playlist.id)}
            disabled={!playlist.is_enabled}
            title={playlist.is_enabled ? undefined : 'Turned off: turn it on to run it'}
          >
            Run
          </Button>
        </div>
      </header>
      <RunProblem playlist={playlist} />

      {isLoading ? (
        <div style={{ padding: 18 }}>
          <Skeleton active paragraph={{ rows: 3 }} title={false} />
        </div>
      ) : isError ? (
        <p style={{ padding: '14px 18px', margin: 0, color: 'var(--ink-2)' }}>
          Couldn't load this playlist's shows. Reload the page to try again.
        </p>
      ) : parts.length === 0 ? (
        <p style={{ padding: '14px 18px', margin: 0, color: 'var(--ink-2)' }}>
          No shows yet. <Link to={`/playlists/${playlist.id}`}>Add shows to {playlist.name}</Link>
        </p>
      ) : (
        <ol className="pm-parts">
          {parts.map((part, i) => (
            <PartRow
              key={part.id}
              part={part}
              index={i}
              kind={playlist.kind}
              enabled={playlist.is_enabled}
              orderMatters={playlist.arrangement === 'by_position'}
            />
          ))}
        </ol>
      )}
    </section>
  );
}
