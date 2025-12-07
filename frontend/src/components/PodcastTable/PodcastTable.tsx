import { useState, useEffect, useMemo } from 'react';
import { Table, Avatar, Switch, message, Typography, Space, Tag, Grid, Drawer, Form, Divider, Card, Segmented, Empty, Input, Button, Popconfirm } from 'antd';
import type { TableProps } from 'antd';
import { RightOutlined, AppstoreOutlined, UnorderedListOutlined, SearchOutlined, UserDeleteOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import type { Podcast, PodcastCategory } from '../../types';
import { CategorySelect } from './CategorySelect';
import { useUpdatePodcast, useUnfollowPodcast } from '../../hooks';

dayjs.extend(relativeTime);

const { useBreakpoint } = Grid;
const { Text } = Typography;

interface PodcastTableProps {
  podcasts: Podcast[];
  loading?: boolean;
}

type ViewMode = 'cards' | 'table';

export function PodcastTable({ podcasts, loading }: PodcastTableProps) {
  const updatePodcast = useUpdatePodcast();
  const unfollowPodcast = useUnfollowPodcast();
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [selectedPodcast, setSelectedPodcast] = useState<Podcast | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [pageSize, setPageSize] = useState(20);
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [viewMode, setViewMode] = useState<ViewMode>('cards');

  // Default to cards on mobile, table on desktop
  useEffect(() => {
    setViewMode(isMobile ? 'cards' : 'table');
  }, [isMobile]);

  // Filter podcasts by search query
  const filteredPodcasts = useMemo(() => {
    if (!searchQuery.trim()) {
      return podcasts;
    }

    const query = searchQuery.toLowerCase();
    return podcasts.filter(
      (podcast) =>
        podcast.name.toLowerCase().includes(query) ||
        (podcast.publisher?.toLowerCase().includes(query) ?? false)
    );
  }, [podcasts, searchQuery]);

  const openPodcastDrawer = (podcast: Podcast) => {
    setSelectedPodcast(podcast);
    setDrawerOpen(true);
  };

  const closePodcastDrawer = () => {
    setDrawerOpen(false);
    setSelectedPodcast(null);
  };

  const handleCategoryChange = async (spotifyId: string, category: PodcastCategory) => {
    setUpdatingId(spotifyId);
    try {
      await updatePodcast.mutateAsync({ spotifyId, data: { category } });
      message.success('Category updated');
    } catch {
      message.error('Failed to update category');
    } finally {
      setUpdatingId(null);
    }
  };

  const handleSequentialChange = async (spotifyId: string, checked: boolean) => {
    setUpdatingId(spotifyId);
    try {
      await updatePodcast.mutateAsync({ spotifyId, data: { is_sequential: checked } });
      message.success(checked ? 'Marked as sequential' : 'Removed sequential flag');
    } catch {
      message.error('Failed to update');
    } finally {
      setUpdatingId(null);
    }
  };

  const handleWeekendOnlyChange = async (spotifyId: string, checked: boolean) => {
    setUpdatingId(spotifyId);
    try {
      await updatePodcast.mutateAsync({ spotifyId, data: { is_weekend_only: checked } });
      message.success(checked ? 'Marked as weekend only' : 'Removed weekend flag');
    } catch {
      message.error('Failed to update');
    } finally {
      setUpdatingId(null);
    }
  };

  const handleUnfollow = async (spotifyId: string, podcastName: string) => {
    setUpdatingId(spotifyId);
    try {
      await unfollowPodcast.mutateAsync(spotifyId);
      message.success(`Unfollowed "${podcastName}"`);
      closePodcastDrawer();
    } catch {
      message.error('Failed to unfollow podcast');
    } finally {
      setUpdatingId(null);
    }
  };

  const columns: TableProps<Podcast>['columns'] = [
    {
      title: 'Podcast',
      key: 'podcast',
      render: (_, record) => (
        <Space size={12}>
          <Avatar
            className="podcast-avatar"
            src={record.image_url}
            size={48}
            shape="square"
            style={{ borderRadius: 8, flexShrink: 0 }}
          >
            {record.name[0]}
          </Avatar>
          <div style={{ minWidth: 0, flex: 1 }}>
            <Text className="podcast-name" strong style={{ display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {record.name}
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {record.publisher}
            </Text>
          </div>
        </Space>
      ),
    },
    {
      title: 'Episodes',
      key: 'episodes',
      align: 'center',
      width: 120,
      render: (_, record) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Tag color="default">{record.total_episodes} total</Tag>
          <Tag color="blue">{record.unplayed_episodes} unplayed</Tag>
        </Space>
      ),
      sorter: (a, b) => a.unplayed_episodes - b.unplayed_episodes,
    },
    {
      title: 'Category',
      key: 'category',
      width: 130,
      render: (_, record) => (
        <CategorySelect
          value={record.category}
          onChange={(value) => handleCategoryChange(record.spotify_id, value)}
          loading={updatingId === record.spotify_id}
        />
      ),
      filters: [
        { text: 'Primary', value: 'primary' },
        { text: 'News', value: 'news' },
        { text: 'Background', value: 'background' },
        { text: 'None', value: 'none' },
      ],
      onFilter: (value, record) => record.category === value,
    },
    {
      title: 'Sequential',
      key: 'is_sequential',
      align: 'center',
      width: 100,
      render: (_, record) => (
        <Switch
          checked={record.is_sequential}
          onChange={(checked) => handleSequentialChange(record.spotify_id, checked)}
          loading={updatingId === record.spotify_id}
          size="small"
        />
      ),
      filters: [
        { text: 'Yes', value: true },
        { text: 'No', value: false },
      ],
      onFilter: (value, record) => record.is_sequential === value,
    },
    {
      title: 'Weekend Only',
      key: 'is_weekend_only',
      align: 'center',
      width: 120,
      render: (_, record) => (
        <Switch
          checked={record.is_weekend_only}
          onChange={(checked) => handleWeekendOnlyChange(record.spotify_id, checked)}
          loading={updatingId === record.spotify_id}
          size="small"
        />
      ),
      filters: [
        { text: 'Yes', value: true },
        { text: 'No', value: false },
      ],
      onFilter: (value, record) => record.is_weekend_only === value,
    },
    {
      title: 'Last Synced',
      key: 'last_synced_at',
      width: 120,
      render: (_, record) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {record.last_synced_at
            ? dayjs(record.last_synced_at).fromNow()
            : 'Never'}
        </Text>
      ),
      sorter: (a, b) => {
        if (!a.last_synced_at) return 1;
        if (!b.last_synced_at) return -1;
        return new Date(a.last_synced_at).getTime() - new Date(b.last_synced_at).getTime();
      },
    },
    {
      title: 'Actions',
      key: 'actions',
      align: 'center',
      width: 100,
      render: (_, record) => (
        <Popconfirm
          title="Unfollow podcast"
          description={`Are you sure you want to unfollow "${record.name}"? This will remove it from Spotify and delete it from this app.`}
          onConfirm={() => handleUnfollow(record.spotify_id, record.name)}
          okText="Unfollow"
          cancelText="Cancel"
          okButtonProps={{ danger: true }}
        >
          <Button
            danger
            icon={<UserDeleteOutlined />}
            loading={updatingId === record.spotify_id}
            size="small"
          />
        </Popconfirm>
      ),
    },
  ];

  // Card view for mobile
  const renderCardView = () => {
    if (filteredPodcasts.length === 0) {
      return <Empty description={searchQuery ? "No podcasts match your search" : "No podcasts found"} />;
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filteredPodcasts.map((podcast) => (
          <Card
            key={podcast.spotify_id}
            size="small"
            hoverable
            onClick={() => openPodcastDrawer(podcast)}
            style={{ cursor: 'pointer', overflow: 'hidden' }}
            styles={{ body: { padding: 12 } }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Avatar
                src={podcast.image_url}
                size={48}
                shape="square"
                style={{ borderRadius: 8, flexShrink: 0 }}
              >
                {podcast.name[0]}
              </Avatar>
              <div style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>
                <div style={{
                  fontWeight: 600,
                  marginBottom: 2,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}>
                  {podcast.name}
                </div>
                <div style={{
                  fontSize: 12,
                  color: 'rgba(0, 0, 0, 0.45)',
                  marginBottom: 4,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}>
                  {podcast.publisher}
                </div>
                <Space size={4} wrap>
                  <Tag
                    color={
                      podcast.category === 'primary' ? 'blue' :
                      podcast.category === 'news' ? 'green' :
                      podcast.category === 'background' ? 'purple' : 'default'
                    }
                    style={{ margin: 0 }}
                  >
                    {podcast.category}
                  </Tag>
                  <Tag color="default" style={{ margin: 0 }}>{podcast.total_episodes} eps</Tag>
                  <Tag color="blue" style={{ margin: 0 }}>{podcast.unplayed_episodes} unplayed</Tag>
                  {podcast.is_sequential && <Tag color="orange" style={{ margin: 0 }}>Seq</Tag>}
                  {podcast.is_weekend_only && <Tag color="purple" style={{ margin: 0 }}>Wknd</Tag>}
                </Space>
              </div>
              <RightOutlined style={{ color: '#999', fontSize: 12, flexShrink: 0 }} />
            </div>
          </Card>
        ))}
      </div>
    );
  };

  return (
    <>
      {/* Search and View Toggle */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 16,
        gap: 12,
        flexWrap: 'wrap'
      }}>
        <Input
          placeholder="Search podcasts by name or publisher..."
          prefix={<SearchOutlined />}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          allowClear
          style={{ flex: 1, minWidth: 200, maxWidth: 400 }}
          size={isMobile ? 'middle' : 'large'}
        />
        <Segmented
          value={viewMode}
          onChange={(value) => setViewMode(value as ViewMode)}
          options={[
            { value: 'cards', icon: <AppstoreOutlined /> },
            { value: 'table', icon: <UnorderedListOutlined /> },
          ]}
          size={isMobile ? 'small' : 'middle'}
        />
      </div>

      {/* Card View */}
      {viewMode === 'cards' && renderCardView()}

      {/* Table View */}
      {viewMode === 'table' && (
        <div style={{ overflowX: 'auto' }}>
          <Table
            dataSource={filteredPodcasts}
            columns={columns}
            rowKey="spotify_id"
            loading={loading}
            pagination={{
              pageSize: pageSize,
              showSizeChanger: true,
              pageSizeOptions: ['10', '20', '50', '100'],
              showTotal: (total, range) => `${range[0]}-${range[1]} of ${total} podcasts`,
              onShowSizeChange: (_, size) => setPageSize(size),
            }}
            size="middle"
            rowClassName={(record) => {
              return record.category !== 'none' ? `category-${record.category}` : '';
            }}
          />
        </div>
      )}

      {/* Settings Drawer */}
      <Drawer
        title="Podcast Settings"
        placement="bottom"
        onClose={closePodcastDrawer}
        open={drawerOpen}
        height="auto"
        styles={{
          body: { paddingBottom: 24 },
        }}
      >
        {selectedPodcast && (
          <div>
            <Space style={{ marginBottom: 16 }}>
              <Avatar
                src={selectedPodcast.image_url}
                size={56}
                shape="square"
                style={{ borderRadius: 8 }}
              >
                {selectedPodcast.name[0]}
              </Avatar>
              <div>
                <Text strong style={{ fontSize: 16, display: 'block' }}>
                  {selectedPodcast.name}
                </Text>
                <Text type="secondary">{selectedPodcast.publisher}</Text>
              </div>
            </Space>

            <Divider style={{ margin: '16px 0' }} />

            <Form layout="vertical">
              <Form.Item label="Category" style={{ marginBottom: 16 }}>
                <CategorySelect
                  value={selectedPodcast.category}
                  onChange={(value) => {
                    handleCategoryChange(selectedPodcast.spotify_id, value);
                    setSelectedPodcast({ ...selectedPodcast, category: value });
                  }}
                  loading={updatingId === selectedPodcast.spotify_id}
                />
              </Form.Item>

              <Form.Item
                label="Sequential"
                extra="Play episodes in order (oldest first)"
                style={{ marginBottom: 16 }}
              >
                <Switch
                  checked={selectedPodcast.is_sequential}
                  onChange={(checked) => {
                    handleSequentialChange(selectedPodcast.spotify_id, checked);
                    setSelectedPodcast({ ...selectedPodcast, is_sequential: checked });
                  }}
                  loading={updatingId === selectedPodcast.spotify_id}
                />
              </Form.Item>

              <Form.Item
                label="Weekend Only"
                extra="Only add to playlists on weekends/holidays"
                style={{ marginBottom: 16 }}
              >
                <Switch
                  checked={selectedPodcast.is_weekend_only}
                  onChange={(checked) => {
                    handleWeekendOnlyChange(selectedPodcast.spotify_id, checked);
                    setSelectedPodcast({ ...selectedPodcast, is_weekend_only: checked });
                  }}
                  loading={updatingId === selectedPodcast.spotify_id}
                />
              </Form.Item>

              <Divider style={{ margin: '16px 0' }} />

              <Space direction="vertical" size={4} style={{ marginBottom: 16 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {selectedPodcast.total_episodes} episodes
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Last synced: {selectedPodcast.last_synced_at
                    ? dayjs(selectedPodcast.last_synced_at).fromNow()
                    : 'Never'}
                </Text>
              </Space>

              <Divider style={{ margin: '16px 0' }} />

              <Popconfirm
                title="Unfollow podcast"
                description={`Are you sure you want to unfollow "${selectedPodcast.name}"? This will remove it from Spotify and delete it from this app.`}
                onConfirm={() => handleUnfollow(selectedPodcast.spotify_id, selectedPodcast.name)}
                okText="Unfollow"
                cancelText="Cancel"
                okButtonProps={{ danger: true }}
              >
                <Button
                  danger
                  icon={<UserDeleteOutlined />}
                  loading={updatingId === selectedPodcast.spotify_id}
                  block
                >
                  Unfollow Podcast
                </Button>
              </Popconfirm>
            </Form>
          </div>
        )}
      </Drawer>
    </>
  );
}
