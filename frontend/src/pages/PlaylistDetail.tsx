import { useState } from 'react';
import {
  Alert,
  Skeleton,
  Button,
  Card,
  Descriptions,
  Grid,
  Space,
  Tooltip,
  Typography,
} from 'antd';
import {
  ArrowLeftOutlined,
  EditOutlined,
  ExportOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import { Link, useParams } from 'react-router';
import dayjs from 'dayjs';
import { usePlaylist, usePlaylistPodcasts, useRunPlaylistWithFeedback } from '../hooks';
import {
  LoadingSpinner,
  PartRow,
  PlaylistFormModal,
  PlaylistStatus,
  RunProblem,
  SleepTag,
} from '../components';
import { getErrorMessage } from '../api';
import {
  arrangementLabel,
  dateDirectionLabel,
  episodeLimitLabel,
  pickFromLabel,
  spotifyPlaylistUrl,
} from '../utils/playlistLabels';
import type { Playlist } from '../types';

const { Title, Text } = Typography;
const { useBreakpoint } = Grid;

// Read-only view of the playlist's podcasts with the rule each one resolves
// to. Editing (membership, order, per-row overrides) lives in the shared
// PlaylistFormModal so there is exactly one place that changes a playlist.
function PodcastsSection({ playlist, onEdit }: { playlist: Playlist; onEdit: () => void }) {
  const { data: podcasts, isLoading, error } = usePlaylistPodcasts(playlist.id);
  const orderMatters = playlist.arrangement === 'by_position';

  return (
    <Card
      title={`Podcasts (${podcasts?.length ?? playlist.podcast_count})`}
      extra={
        <Button size="small" icon={<EditOutlined />} onClick={onEdit}>
          Edit podcasts
        </Button>
      }
    >
      {error ? (
        <Alert
          type="error"
          message="Failed to load podcasts"
          description={getErrorMessage(error)}
          showIcon
        />
      ) : (
        <>
          {!orderMatters && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={
                playlist.arrangement === 'shuffle'
                  ? 'This playlist is shuffled, so the order below is not used.'
                  : 'This playlist is arranged by release date, so the order below is not used.'
              }
            />
          )}
          {isLoading ? (
            <Skeleton active paragraph={{ rows: 4 }} title={false} />
          ) : (podcasts ?? []).length === 0 ? (
            <p style={{ margin: 0, color: 'var(--ink-2)' }}>
              No podcasts yet. Use Edit podcasts to add some.
            </p>
          ) : (
            <ol className="pm-parts pm-parts-in-card">
              {(podcasts ?? []).map((part, i) => (
                <PartRow
                  key={part.id}
                  part={part}
                  index={i}
                  kind={playlist.kind}
                  enabled={playlist.is_enabled}
                  orderMatters={orderMatters}
                />
              ))}
            </ol>
          )}
        </>
      )}
    </Card>
  );
}

export function PlaylistDetail() {
  const { id } = useParams();
  const playlistId = Number(id);
  const validId = Number.isInteger(playlistId) && playlistId > 0;
  const { data: playlist, isLoading, error } = usePlaylist(validId ? playlistId : 0);
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [isEditOpen, setIsEditOpen] = useState(false);

  const { run, isRunning } = useRunPlaylistWithFeedback();
  const handleRun = () => {
    if (playlist) void run(playlist.id);
  };

  const backLink = (
    <Link to="/playlists">
      <ArrowLeftOutlined /> Playlists
    </Link>
  );

  if (!validId) {
    return (
      <Alert
        type="error"
        message="Playlist not found"
        description={<Space direction="vertical">{backLink}</Space>}
        showIcon
      />
    );
  }

  if (isLoading) {
    return <LoadingSpinner tip="Loading playlist..." />;
  }

  if (error || !playlist) {
    return (
      <Alert
        type="error"
        message="Failed to load playlist"
        description={
          <Space direction="vertical">
            <Text>{error ? getErrorMessage(error) : 'This playlist does not exist.'}</Text>
            {backLink}
          </Space>
        }
        showIcon
      />
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 8 }}>{backLink}</div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 24,
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <Title level={4} style={{ marginBottom: 4 }}>
            {playlist.name}
            {playlist.kind === 'sleep' && (
              <SleepTag style={{ marginLeft: 8, verticalAlign: 'middle' }} />
            )}
          </Title>
          <Text type="secondary">
            {playlist.podcast_count} podcast{playlist.podcast_count !== 1 ? 's' : ''} ·{' '}
            {arrangementLabel(playlist)}
          </Text>
        </div>
        <Space wrap>
          {/* Disabled playlists are never written to on Spotify, manual runs
              included (issue #239) — the backend refuses them with a 409.
              The span is the tooltip's trigger: antd 6 no longer wraps a
              disabled child, and a disabled <button> fires no mouse events.
              When it is disabled the span is focusable and carries the
              explanation, and the tooltip opens on focus too, so the reason
              reaches keyboard and screen-reader users as well as hover. */}
          <Tooltip
            title={playlist.is_enabled ? undefined : 'Disabled — enable it to run it'}
            trigger={['hover', 'focus']}
          >
            <span
              style={{
                display: 'inline-block',
                cursor: playlist.is_enabled ? undefined : 'not-allowed',
              }}
              tabIndex={playlist.is_enabled ? undefined : 0}
              role={playlist.is_enabled ? undefined : 'button'}
              aria-disabled={playlist.is_enabled ? undefined : true}
              aria-label={
                playlist.is_enabled ? undefined : 'Run: unavailable, this playlist is disabled'
              }
            >
              <Button
                icon={<PlayCircleOutlined />}
                onClick={handleRun}
                loading={isRunning(playlist.id)}
                disabled={!playlist.is_enabled}
                style={playlist.is_enabled ? undefined : { pointerEvents: 'none' }}
                aria-hidden={playlist.is_enabled ? undefined : true}
              >
                Run
              </Button>
            </span>
          </Tooltip>
          <Button icon={<EditOutlined />} onClick={() => setIsEditOpen(true)}>
            Edit
          </Button>
          {playlist.spotify_playlist_id && (
            <Button
              icon={<ExportOutlined />}
              href={spotifyPlaylistUrl(playlist.spotify_playlist_id) ?? undefined}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open in Spotify
            </Button>
          )}
        </Space>
      </div>

      <Card title="Settings" style={{ marginBottom: 24 }} styles={{ body: { padding: 0 } }}>
        <RunProblem playlist={playlist} />
        <div style={{ padding: 24 }}>
          <Descriptions column={isMobile ? 1 : 2} size="small">
            <Descriptions.Item label="Kind">
              {playlist.kind === 'sleep'
                ? "Sleep — only episodes you've already finished"
                : "Standard — episodes you haven't finished"}
            </Descriptions.Item>
            <Descriptions.Item label="Arrangement">{arrangementLabel(playlist)}</Descriptions.Item>
            {playlist.arrangement === 'by_date' && (
              <Descriptions.Item label="Direction">
                {dateDirectionLabel(playlist.date_direction)}
              </Descriptions.Item>
            )}
            <Descriptions.Item label="Default episodes">
              {episodeLimitLabel(playlist.default_episode_limit, playlist.kind)}
            </Descriptions.Item>
            <Descriptions.Item label="Take from">
              {pickFromLabel(playlist.default_pick_from)}
            </Descriptions.Item>
            <Descriptions.Item label="Last run">
              <Space size={10} wrap>
                <PlaylistStatus playlist={playlist} />
                {playlist.is_enabled ? null : (
                  <Text type="secondary">Never written to on Spotify until turned on</Text>
                )}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="Last written to Spotify">
              {playlist.last_updated_at ? (
                <Tooltip title={dayjs(playlist.last_updated_at).format('YYYY-MM-DD HH:mm:ss')}>
                  {dayjs(playlist.last_updated_at).fromNow()}
                </Tooltip>
              ) : (
                'Never'
              )}
            </Descriptions.Item>
          </Descriptions>
        </div>
      </Card>

      <PodcastsSection playlist={playlist} onEdit={() => setIsEditOpen(true)} />

      <PlaylistFormModal
        open={isEditOpen}
        playlist={playlist}
        onClose={() => setIsEditOpen(false)}
      />
    </div>
  );
}
