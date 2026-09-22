import { App, Card, Row, Col, Statistic, Button, Space, Typography, Tag, Grid } from 'antd';
import {
  SyncOutlined,
  CustomerServiceOutlined,
  UnorderedListOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  ExportOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { usePodcasts, useSyncPodcasts, usePlaylists, useRunAllPlaylists } from '../hooks';
import { LoadingSpinner } from '../components';
import { getErrorMessage } from '../api';
import { ruleSummary, spotifyPlaylistUrl } from '../utils/playlistLabels';

const { Title, Text } = Typography;
const { useBreakpoint } = Grid;

export function Dashboard() {
  const { message } = App.useApp();
  const { data: podcasts, isLoading: podcastsLoading } = usePodcasts();
  const { data: playlists, isLoading: playlistsLoading } = usePlaylists();
  const syncPodcasts = useSyncPodcasts();
  const runAllPlaylists = useRunAllPlaylists();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const handleSync = async () => {
    try {
      const result = await syncPodcasts.mutateAsync();
      message.success(result.message);
    } catch {
      message.error('Failed to sync podcasts');
    }
  };

  const handleRunAll = async () => {
    try {
      const result = await runAllPlaylists.mutateAsync();
      // A 200 only means the batch ran — each playlist carries its own
      // success/skipped/error status, so summarise rather than blanket-success.
      const failed = result.results.filter((r) => !r.success);
      const skipped = result.results.filter((r) => r.success && r.skipped);
      const succeeded = result.results.filter((r) => r.success && !r.skipped);

      let summary = `Updated ${succeeded.length} playlist${succeeded.length === 1 ? '' : 's'}`;
      if (skipped.length > 0) {
        summary += `, ${skipped.length} skipped (weekend-only)`;
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
      message.error(getErrorMessage(err));
    }
  };

  if (podcastsLoading || playlistsLoading) {
    return <LoadingSpinner tip="Loading dashboard..." />;
  }

  // Calculate stats
  const totalPodcasts = podcasts?.length || 0;
  const assignedPodcasts = podcasts?.filter((p) => p.playlist_ids.length > 0).length || 0;
  const unassignedPodcasts = totalPodcasts - assignedPodcasts;

  // Find last sync time
  const lastSyncedPodcast = podcasts
    ?.filter((p) => p.last_synced_at)
    .sort(
      (a, b) => new Date(b.last_synced_at!).getTime() - new Date(a.last_synced_at!).getTime()
    )[0];

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>
        Dashboard
      </Title>

      {/* Quick Actions */}
      <Card
        title={isMobile ? 'Quick Actions' : undefined}
        style={{ marginBottom: 16 }}
        styles={{ body: { padding: isMobile ? 12 : 24 } }}
      >
        <Space
          direction={isMobile ? 'vertical' : 'horizontal'}
          style={{ width: isMobile ? '100%' : 'auto' }}
        >
          <Button
            type="primary"
            icon={<SyncOutlined spin={syncPodcasts.isPending} />}
            onClick={handleSync}
            loading={syncPodcasts.isPending}
            size={isMobile ? 'large' : 'middle'}
            block={isMobile}
          >
            {isMobile ? 'Sync Podcasts' : 'Sync Podcasts from Spotify'}
          </Button>
          <Button
            icon={<ThunderboltOutlined />}
            onClick={handleRunAll}
            loading={runAllPlaylists.isPending}
            size={isMobile ? 'large' : 'middle'}
            block={isMobile}
          >
            Update All Playlists
          </Button>
        </Space>
      </Card>

      {/* Stats Cards */}
      <Row gutter={[isMobile ? 12 : 16, isMobile ? 12 : 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card styles={{ body: { padding: isMobile ? 16 : 24 } }}>
            <Statistic
              title="Total Podcasts"
              value={totalPodcasts}
              prefix={<CustomerServiceOutlined />}
              valueStyle={{ fontSize: isMobile ? 28 : 24 }}
            />
            {lastSyncedPodcast && (
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
                Last synced {dayjs(lastSyncedPodcast.last_synced_at).fromNow()}
              </Text>
            )}
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card styles={{ body: { padding: isMobile ? 16 : 24 } }}>
            <Statistic
              title="Assigned to Playlists"
              value={assignedPodcasts}
              suffix={`/ ${totalPodcasts}`}
              valueStyle={{
                color: assignedPodcasts === totalPodcasts ? '#52c41a' : '#1890ff',
                fontSize: isMobile ? 28 : 24,
              }}
            />
            {assignedPodcasts === totalPodcasts && totalPodcasts > 0 && (
              <Tag icon={<CheckCircleOutlined />} color="success" style={{ marginTop: 8 }}>
                All assigned!
              </Tag>
            )}
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card styles={{ body: { padding: isMobile ? 16 : 24 } }}>
            <Statistic
              title="Managed Playlists"
              value={playlists?.length || 0}
              prefix={<UnorderedListOutlined />}
              valueStyle={{ fontSize: isMobile ? 28 : 24 }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card styles={{ body: { padding: isMobile ? 16 : 24 } }}>
            <Statistic
              title="Unassigned"
              value={unassignedPodcasts}
              valueStyle={{
                color: unassignedPodcasts === 0 ? '#52c41a' : '#faad14',
                fontSize: isMobile ? 28 : 24,
              }}
            />
            {unassignedPodcasts > 0 && (
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
                {unassignedPodcasts} podcast{unassignedPodcasts !== 1 ? 's' : ''} not in any
                playlist
              </Text>
            )}
          </Card>
        </Col>
      </Row>

      {/* Playlists Status */}
      {playlists && playlists.length > 0 && (
        <Card
          title="Playlist Status"
          style={{ marginTop: isMobile ? 16 : 24 }}
          styles={{ body: { padding: isMobile ? 12 : 24 } }}
        >
          <Row gutter={[isMobile ? 8 : 16, isMobile ? 8 : 16]}>
            {playlists.map((playlist) => (
              <Col xs={24} sm={12} lg={6} key={playlist.id}>
                <Card size="small" bordered styles={{ body: { padding: isMobile ? 12 : 16 } }}>
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <Text strong style={{ fontSize: isMobile ? 15 : 14 }}>
                      {playlist.name}
                    </Text>
                    <Space size={4} wrap>
                      <Tag
                        color={playlist.default_episode_limit === 0 ? 'blue' : 'green'}
                        style={{ width: 'fit-content' }}
                      >
                        {ruleSummary(playlist.default_episode_limit, playlist.default_pick_from)}
                      </Tag>
                      {playlist.is_weekend_only && (
                        <Tag color="orange" style={{ width: 'fit-content' }}>
                          Weekend
                        </Tag>
                      )}
                    </Space>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {playlist.podcast_count} podcast{playlist.podcast_count !== 1 ? 's' : ''}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {playlist.last_updated_at
                        ? `Updated ${dayjs(playlist.last_updated_at).fromNow()}`
                        : 'Never updated'}
                    </Text>
                    {!playlist.is_enabled && (
                      <Tag color="default" style={{ width: 'fit-content' }}>
                        Disabled
                      </Tag>
                    )}
                    {spotifyPlaylistUrl(playlist.spotify_playlist_id) && (
                      <a
                        href={spotifyPlaylistUrl(playlist.spotify_playlist_id) ?? undefined}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ fontSize: 12 }}
                      >
                        Open in Spotify <ExportOutlined />
                      </a>
                    )}
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        </Card>
      )}
    </div>
  );
}
