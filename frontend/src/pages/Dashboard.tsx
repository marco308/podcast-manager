import { Card, Row, Col, Statistic, Button, Space, Typography, Tag, message } from 'antd';
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

export function Dashboard() {
  const { data: podcasts, isLoading: podcastsLoading } = usePodcasts();
  const { data: playlists, isLoading: playlistsLoading } = usePlaylists();
  const syncPodcasts = useSyncPodcasts();
  const runAllPlaylists = useRunAllPlaylists();

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
  const categorizedPodcasts = podcasts?.filter((p) => p.category !== 'none').length || 0;
  const primaryCount = podcasts?.filter((p) => p.category === 'primary').length || 0;
  const newsCount = podcasts?.filter((p) => p.category === 'news').length || 0;
  const backgroundCount = podcasts?.filter((p) => p.category === 'background').length || 0;

  // Find last sync time
  const lastSyncedPodcast = podcasts
    ?.filter((p) => p.last_synced_at)
    .sort((a, b) => 
      new Date(b.last_synced_at!).getTime() - new Date(a.last_synced_at!).getTime()
    )[0];

  return (
    <div>
      <Title level={4}>Dashboard</Title>

      {/* Quick Actions */}
      <Card style={{ marginBottom: 24 }}>
        <Space>
          <Button
            type="primary"
            icon={<SyncOutlined spin={syncPodcasts.isPending} />}
            onClick={handleSync}
            loading={syncPodcasts.isPending}
          >
            Sync Podcasts from Spotify
          </Button>
          <Button
            icon={<ThunderboltOutlined />}
            onClick={handleRunAll}
            loading={runAllPlaylists.isPending}
          >
            Update All Playlists
          </Button>
        </Space>
      </Card>

      {/* Stats Cards */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Total Podcasts"
              value={totalPodcasts}
              prefix={<CustomerServiceOutlined />}
            />
            {lastSyncedPodcast && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                Last synced {dayjs(lastSyncedPodcast.last_synced_at).fromNow()}
              </Text>
            )}
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Categorized"
              value={categorizedPodcasts}
              suffix={`/ ${totalPodcasts}`}
              valueStyle={{ color: categorizedPodcasts === totalPodcasts ? '#52c41a' : '#1890ff' }}
            />
            {categorizedPodcasts === totalPodcasts && (
              <Tag icon={<CheckCircleOutlined />} color="success">
                All categorized!
              </Tag>
            )}
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Managed Playlists"
              value={playlists?.length || 0}
              prefix={<UnorderedListOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Space direction="vertical" size={0}>
              <Text type="secondary">Categories</Text>
              <div style={{ marginTop: 8 }}>
                <Tag color="blue">Primary: {primaryCount}</Tag>
                <Tag color="green">News: {newsCount}</Tag>
                <Tag color="purple">Background: {backgroundCount}</Tag>
              </div>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* Playlists Status */}
      {playlists && playlists.length > 0 && (
        <Card title="Playlist Status" style={{ marginTop: 24 }}>
          <Row gutter={[16, 16]}>
            {playlists.map((playlist) => (
              <Col xs={24} sm={12} lg={6} key={playlist.id}>
                <Card size="small" bordered>
                  <Space direction="vertical" size={0}>
                    <Text strong>{playlist.name}</Text>
                    <Tag color={
                      playlist.rule_type === 'primary' ? 'blue' :
                      playlist.rule_type === 'news' ? 'green' :
                      playlist.rule_type === 'background' ? 'purple' : 'default'
                    }>
                      {playlist.rule_type}
                    </Tag>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {playlist.last_updated_at
                        ? `Updated ${dayjs(playlist.last_updated_at).fromNow()}`
                        : 'Never updated'}
                    </Text>
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
