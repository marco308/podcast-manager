import { Button } from 'antd';
import { SyncOutlined } from '@ant-design/icons';
import { Link } from 'react-router';
import dayjs from 'dayjs';
import {
  usePodcasts,
  usePlaylists,
  useJobs,
  useSyncPodcastsWithFeedback,
  useRunAllPlaylistsWithFeedback,
} from '../hooks';
import { LoadingSpinner, PlaylistAssembly } from '../components';

const DAILY_JOB_ID = 'daily_playlist_update';

function runTime(iso: string | null | undefined): string {
  if (!iso) return 'Not yet';
  const t = dayjs(iso);
  return t.isSame(dayjs(), 'day') ? t.format('HH:mm') : t.format('HH:mm ddd');
}

// The run sheet: answers "did last night work?" before anything is clicked,
// then every playlist as a parts list of its shows.
export function Dashboard() {
  const { data: podcasts, isLoading: podcastsLoading } = usePodcasts();
  const { data: playlists, isLoading: playlistsLoading } = usePlaylists();
  const { data: jobs } = useJobs();
  const { sync: handleSync, isPending: syncPending } = useSyncPodcastsWithFeedback();
  const { runAll: handleRunAll, isPending: runAllPending } = useRunAllPlaylistsWithFeedback();

  if (podcastsLoading || playlistsLoading) {
    return <LoadingSpinner tip="Loading the run sheet…" />;
  }

  const daily = jobs?.jobs.find((j) => j.id === DAILY_JOB_ID);
  const troubled = (playlists ?? []).filter(
    (p) => p.is_enabled && (p.last_run_status === 'partial' || p.last_run_status === 'failed')
  );
  const unsorted = (podcasts ?? []).filter((p) => p.playlist_ids.length === 0).length;
  const dailyFailed = daily?.last_run_status === 'failed';

  return (
    <div style={{ display: 'grid', gap: 24 }}>
      <header
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 16,
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          borderBottom: '3px solid var(--rule-strong)',
          paddingBottom: 18,
        }}
      >
        <div>
          <h1 className="pm-title">Run sheet</h1>
          <div className="pm-label" style={{ marginTop: 10 }}>
            {dayjs().format('ddd D MMM')}
          </div>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          <Button
            icon={<SyncOutlined spin={syncPending} />}
            onClick={handleSync}
            loading={syncPending}
          >
            Sync library
          </Button>
          <Button type="primary" onClick={handleRunAll} loading={runAllPending}>
            Update all
          </Button>
        </div>
      </header>

      <section className="pm-runsheet" aria-label="Run sheet">
        <div>
          <span className="pm-label">Last run</span>
          <b className="pm-num" style={dailyFailed ? { color: 'var(--failed)' } : undefined}>
            {runTime(daily?.last_run)}
          </b>
          {daily?.last_run_status === 'failed' && (
            <span className="pm-label" style={{ color: 'var(--ink)' }}>
              Failed
              {daily.last_run_failed_steps?.length
                ? `: ${daily.last_run_failed_steps.join(', ')}`
                : ''}
            </span>
          )}
        </div>
        <div>
          <span className="pm-label">Next run</span>
          <b className="pm-num">{runTime(daily?.next_run)}</b>
        </div>
        <div>
          <span className="pm-label">Need a look</span>
          <b className="pm-num" style={troubled.length ? { color: 'var(--partial)' } : undefined}>
            {troubled.length}
          </b>
          {troubled.length > 0 && (
            <span className="pm-label" style={{ color: 'var(--ink)' }}>
              {troubled.map((p) => p.name).join(', ')}
            </span>
          )}
        </div>
        <div>
          <span className="pm-label">Unsorted shows</span>
          <b className="pm-num">{unsorted}</b>
          {unsorted > 0 && (
            <Link to="/podcasts" className="pm-label" style={{ color: 'var(--accent-text)' }}>
              Sort them
            </Link>
          )}
        </div>
      </section>

      {playlists && playlists.length > 0 ? (
        <div className="pm-assemblies">
          {playlists.map((playlist) => (
            <PlaylistAssembly key={playlist.id} playlist={playlist} />
          ))}
        </div>
      ) : (
        <div
          className="pm-sheet"
          style={{ padding: '28px 24px', display: 'grid', gap: 14, justifyItems: 'start' }}
        >
          <h2 className="pm-title" style={{ fontSize: 24 }}>
            No playlists yet
          </h2>
          <p style={{ margin: 0, color: 'var(--ink-2)', maxWidth: '52ch' }}>
            Make a playlist, add shows to it, and it appears here as a parts list: each show
            numbered, with the rule the next rebuild will use.
          </p>
          <Link to="/playlists">
            <Button type="primary">Make a playlist</Button>
          </Link>
        </div>
      )}
    </div>
  );
}
