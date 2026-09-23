import { useState } from 'react';
import {
  Alert,
  Avatar,
  Button,
  Card,
  Descriptions,
  Grid,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { TableProps } from 'antd';
import {
  ArrowLeftOutlined,
  EditOutlined,
  ExportOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import { Link, useParams } from 'react-router';
import dayjs from 'dayjs';
import { usePlaylist, usePlaylistPodcasts, useRunPlaylistWithFeedback } from '../hooks';
import { LoadingSpinner, PlaylistFormModal } from '../components';
import { getErrorMessage } from '../api';
import {
  arrangementLabel,
  dateDirectionLabel,
  episodeLimitLabel,
  pickFromLabel,
  ruleSourceLabel,
  ruleSummary,
  spotifyPlaylistUrl,
} from '../utils/playlistLabels';
import type { Playlist, PlaylistPodcast } from '../types';

const { Title, Text } = Typography;
const { useBreakpoint } = Grid;

function hasOverride(podcast: PlaylistPodcast): boolean {
  return podcast.override.episode_limit !== null || podcast.override.pick_from !== null;
}

// Read-only view of the playlist's podcasts with the rule each one resolves
// to. Editing (membership, order, per-row overrides) lives in the shared
// PlaylistFormModal so there is exactly one place that changes a playlist.
function PodcastsSection({ playlist, onEdit }: { playlist: Playlist; onEdit: () => void }) {
  const { data: podcasts, isLoading, error } = usePlaylistPodcasts(playlist.id);
  const orderMatters = playlist.arrangement === 'by_position';

  const columns: TableProps<PlaylistPodcast>['columns'] = [
    {
      title: '#',
      key: 'position',
      width: 48,
      align: 'center',
      render: (_, __, index) => (
        <Text type={orderMatters ? undefined : 'secondary'}>{index + 1}</Text>
      ),
    },
    {
      title: 'Podcast',
      key: 'podcast',
      render: (_, row) => (
        <Space size={8}>
          {row.image_url ? (
            <Avatar
              src={row.image_url}
              size={32}
              shape="square"
              style={{ borderRadius: 6, flexShrink: 0 }}
            >
              {row.name[0]}
            </Avatar>
          ) : null}
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Text ellipsis style={{ maxWidth: 260 }}>
                {row.name}
              </Text>
              {row.is_sequential && (
                <Tooltip title="Sequential: takes from the oldest unfinished episode unless overridden">
                  <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>
                    SEQ
                  </Tag>
                </Tooltip>
              )}
              {/* Still assigned, but the sync found it gone from the Spotify
                  library, so the next build skips it (issue #240). */}
              {row.missing_since && (
                <Tooltip title="Not in your Spotify library any more — this show contributes no episodes, and will be removed from the app if it stays away">
                  <Tag color="warning" style={{ fontSize: 10, margin: 0 }}>
                    NOT ON SPOTIFY
                  </Tag>
                </Tooltip>
              )}
            </div>
            {row.publisher && (
              <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                {row.publisher}
              </Text>
            )}
          </div>
        </Space>
      ),
    },
    {
      title: 'Rule',
      key: 'rule',
      width: 260,
      render: (_, row) => (
        <Space size={6} wrap>
          <Tag color={hasOverride(row) ? 'purple' : 'default'} style={{ margin: 0 }}>
            {ruleSummary(row.rule.episode_limit, row.rule.pick_from)}
          </Tag>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {ruleSourceLabel(row.rule)}
          </Text>
        </Space>
      ),
    },
  ];

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
          <Table<PlaylistPodcast>
            size="small"
            rowKey="id"
            loading={isLoading}
            pagination={false}
            dataSource={podcasts ?? []}
            columns={columns}
            locale={{ emptyText: 'No podcasts yet. Use Edit podcasts to add some.' }}
            scroll={{ x: 520 }}
          />
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

      <Card title="Settings" style={{ marginBottom: 24 }}>
        <Descriptions column={isMobile ? 1 : 2} size="small">
          <Descriptions.Item label="Arrangement">{arrangementLabel(playlist)}</Descriptions.Item>
          {playlist.arrangement === 'by_date' && (
            <Descriptions.Item label="Direction">
              {dateDirectionLabel(playlist.date_direction)}
            </Descriptions.Item>
          )}
          <Descriptions.Item label="Default episodes">
            {episodeLimitLabel(playlist.default_episode_limit)}
          </Descriptions.Item>
          <Descriptions.Item label="Take from">
            {pickFromLabel(playlist.default_pick_from)}
          </Descriptions.Item>
          <Descriptions.Item label="Enabled">
            {playlist.is_enabled ? (
              <Tag color="success">Enabled</Tag>
            ) : (
              <Space size={6}>
                <Tag color="default">Disabled</Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Never written to on Spotify until re-enabled
                </Text>
              </Space>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Last updated">
            {playlist.last_updated_at ? (
              <Tooltip title={dayjs(playlist.last_updated_at).format('YYYY-MM-DD HH:mm:ss')}>
                {dayjs(playlist.last_updated_at).fromNow()}
              </Tooltip>
            ) : (
              'Never'
            )}
          </Descriptions.Item>
        </Descriptions>
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
