import { Card, Row, Col, Statistic, Button, Space, Typography, Tag, message, Grid } from 'antd';
import {
  SyncOutlined,
  CustomerServiceOutlined,
  UnorderedListOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { usePodcasts, useSyncPodcasts, usePlaylists, useRunAllPlaylists } from '../hooks';
import { LoadingSpinner } from '../components';

dayjs.extend(relativeTime);

const { Title, Text } = Typography;
const { useBreakpoint } = Grid;

export function Dashboard() {
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
      message.success(result.message);
    } catch {
      message.error('Failed to update playlists');
    }
  };

  if (podcastsLoading || playlistsLoading) {
    return <LoadingSpinner tip="Loading dashboard..." />;
  }

  // Calculate stats
  const totalPodcasts = podcasts?.length || 0;
  const categorizedPodcasts = podcasts?.filter((p) => p.categories.length > 0).length || 0;
  const primaryCount = podcasts?.filter((p) => p.categories.includes('primary')).length || 0;
  const newsCount = podcasts?.filter((p) => p.categories.includes('news')).length || 0;
  const backgroundCount = podcasts?.filter((p) => p.categories.includes('background')).length || 0;
  const weekendCount = podcasts?.filter((p) => p.categories.includes('weekend')).length || 0;

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
              title="Categorized"
              value={categorizedPodcasts}
              suffix={`/ ${totalPodcasts}`}
              valueStyle={{
                color: categorizedPodcasts === totalPodcasts ? '#52c41a' : '#1890ff',
                fontSize: isMobile ? 28 : 24,
              }}
            />
            {categorizedPodcasts === totalPodcasts && (
              <Tag icon={<CheckCircleOutlined />} color="success" style={{ marginTop: 8 }}>
                All categorized!
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
            <Space direction="vertical" size={0} style={{ width: '100%' }}>
              <Text type="secondary" style={{ fontSize: isMobile ? 14 : 12 }}>
                Categories
              </Text>
              <div
                style={{
                  marginTop: 8,
                  display: 'flex',
                  flexDirection: isMobile ? 'column' : 'row',
                  gap: 4,
                  flexWrap: 'wrap',
                }}
              >
                <Tag color="blue" style={{ margin: 0 }}>
                  Primary: {primaryCount}
                </Tag>
                <Tag color="green" style={{ margin: 0 }}>
                  News: {newsCount}
                </Tag>
                <Tag color="purple" style={{ margin: 0 }}>
                  Background: {backgroundCount}
                </Tag>
                <Tag color="orange" style={{ margin: 0 }}>
                  Weekend: {weekendCount}
                </Tag>
              </div>
            </Space>
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
                    <Tag
                      color={
                        playlist.rule_type === 'primary'
                          ? 'blue'
                          : playlist.rule_type === 'news'
                            ? 'green'
                            : playlist.rule_type === 'morning'
                              ? 'orange'
                              : playlist.rule_type === 'background'
                                ? 'purple'
                                : 'default'
                      }
                      style={{ width: 'fit-content' }}
                    >
                      {playlist.rule_type}
                    </Tag>
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
