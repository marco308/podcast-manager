import { useState, useEffect, useMemo, useRef } from 'react';
import type { CSSProperties } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  App,
  Table,
  Avatar,
  Switch,
  Typography,
  Space,
  Tag,
  Grid,
  Drawer,
  Form,
  Divider,
  Card,
  Segmented,
  Empty,
  Input,
  Button,
  Popconfirm,
  Select,
} from 'antd';
import type { TableProps } from 'antd';
import {
  RightOutlined,
  AppstoreOutlined,
  UnorderedListOutlined,
  SearchOutlined,
  UserDeleteOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Podcast } from '../../types';
import {
  podcastKeys,
  useUpdatePodcast,
  useUnfollowPodcast,
  usePlaylists,
  useAddPodcastsToPlaylist,
  useRemovePodcastFromPlaylist,
} from '../../hooks';

const { useBreakpoint } = Grid;
const { Text } = Typography;

interface PodcastTableProps {
  podcasts: Podcast[];
}

type ViewMode = 'cards' | 'table';

// The count is only known once a playlist build has read the whole show
// (issue #155); until then say so rather than showing a made-up number.
function UnplayedTag({ count, style }: { count: number | null; style?: CSSProperties }) {
  if (count === null) {
    return (
      <Tag
        color="default"
        style={style}
        title="Counted when a playlist build reads this podcast's full episode list"
      >
        unplayed: not counted
      </Tag>
    );
  }
  return (
    <Tag color="blue" style={style}>
      {count} unplayed
    </Tag>
  );
}

export function PodcastTable({ podcasts }: PodcastTableProps) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const updatePodcast = useUpdatePodcast();
  const unfollowPodcast = useUnfollowPodcast();
  const { data: playlists } = usePlaylists();
  const addPodcastsToPlaylist = useAddPodcastsToPlaylist();
  const removePodcastFromPlaylist = useRemovePodcastFromPlaylist();
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [selectedPodcast, setSelectedPodcast] = useState<Podcast | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [pageSize, setPageSize] = useState(20);
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [viewMode, setViewMode] = useState<ViewMode>('cards');
  const hasUserSelected = useRef(false);

  // Default to cards on mobile, table on desktop (only if user hasn't manually chosen)
  useEffect(() => {
    if (!hasUserSelected.current) {
      setViewMode(isMobile ? 'cards' : 'table');
    }
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

  const playlistOptions = useMemo(() => {
    return (playlists || []).map((p) => ({
      value: p.id,
      label: p.name,
    }));
  }, [playlists]);

  // Helper to get playlist name by id
  const getPlaylistName = (playlistId: number): string => {
    const playlist = playlists?.find((p) => p.id === playlistId);
    return playlist?.name || `Playlist ${playlistId}`;
  };

  const openPodcastDrawer = (podcast: Podcast) => {
    setSelectedPodcast(podcast);
    setDrawerOpen(true);
  };

  const closePodcastDrawer = () => {
    setDrawerOpen(false);
    setSelectedPodcast(null);
  };

  // Optimistically rewrite one podcast's playlist_ids in the cached list so
  // the table Select reflects a change immediately (and a second change diffs
  // against fresh data instead of stale props).
  const setCachedPlaylistIds = (podcastId: number, playlistIds: number[]) => {
    queryClient.setQueryData<Podcast[]>(podcastKeys.list(), (old) =>
      old?.map((p) => (p.id === podcastId ? { ...p, playlist_ids: playlistIds } : p))
    );
  };

  const handlePlaylistsChange = async (podcast: Podcast, newPlaylistIds: number[]) => {
    setUpdatingId(podcast.spotify_id);
    const previousIds = podcast.playlist_ids;
    setCachedPlaylistIds(podcast.id, newPlaylistIds);
    try {
      const oldIds = new Set(previousIds);
      const newIds = new Set(newPlaylistIds);

      // Find IDs to add and remove
      const toAdd = newPlaylistIds.filter((id) => !oldIds.has(id));
      const toRemove = previousIds.filter((id) => !newIds.has(id));

      // Process additions and removals in parallel
      await Promise.all([
        ...toAdd.map((playlistId) =>
          addPodcastsToPlaylist.mutateAsync({
            playlistId,
            podcastIds: [podcast.id],
          })
        ),
        ...toRemove.map((playlistId) =>
          removePodcastFromPlaylist.mutateAsync({
            playlistId,
            podcastId: podcast.id,
          })
        ),
      ]);

      message.success('Playlist assignments updated');
    } catch {
      // Roll back both optimistic copies (cached list and drawer state);
      // successful sub-mutations trigger an invalidation that will settle
      // any partial state from the server.
      setCachedPlaylistIds(podcast.id, previousIds);
      setSelectedPodcast((prev) =>
        prev && prev.id === podcast.id ? { ...prev, playlist_ids: previousIds } : prev
      );
      message.error('Failed to update playlist assignments');
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
      // Roll back the drawer's optimistic toggle to the pre-change value
      setSelectedPodcast((prev) =>
        prev && prev.spotify_id === spotifyId ? { ...prev, is_sequential: !checked } : prev
      );
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
            <Text
              className="podcast-name"
              strong
              style={{
                display: 'block',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
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
          <UnplayedTag count={record.unplayed_episodes} />
        </Space>
      ),
      sorter: (a, b) => (a.unplayed_episodes ?? -1) - (b.unplayed_episodes ?? -1),
    },
    {
      title: 'Playlists',
      key: 'playlists',
      width: 220,
      render: (_, record) => (
        <Select
          mode="multiple"
          value={record.playlist_ids}
          onChange={(value) => handlePlaylistsChange(record, value)}
          loading={updatingId === record.spotify_id}
          style={{ width: 200 }}
          placeholder="Unassigned"
          allowClear
          maxTagCount="responsive"
          options={playlistOptions}
        />
      ),
      filters: [
        ...(playlists || []).map((p) => ({ text: p.name, value: p.id })),
        { text: 'Unassigned', value: -1 },
      ],
      onFilter: (value, record) => {
        if (value === -1) return record.playlist_ids.length === 0;
        return record.playlist_ids.includes(value as number);
      },
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
      title: 'Last Synced',
      key: 'last_synced_at',
      width: 120,
      render: (_, record) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {record.last_synced_at ? dayjs(record.last_synced_at).fromNow() : 'Never'}
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
            aria-label="Unfollow podcast"
          />
        </Popconfirm>
      ),
    },
  ];

  // Card view for mobile
  const renderCardView = () => {
    if (filteredPodcasts.length === 0) {
      return (
        <Empty description={searchQuery ? 'No podcasts match your search' : 'No podcasts found'} />
      );
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
                <div
                  style={{
                    fontWeight: 600,
                    marginBottom: 2,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {podcast.name}
                </div>
                <Text
                  type="secondary"
                  style={{
                    fontSize: 12,
                    marginBottom: 4,
                    display: 'block',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {podcast.publisher}
                </Text>
                <Space size={4} wrap>
                  {podcast.playlist_ids.length > 0 ? (
                    podcast.playlist_ids.map((playlistId) => (
                      <Tag key={playlistId} color="blue" style={{ margin: 0 }}>
                        {getPlaylistName(playlistId)}
                      </Tag>
                    ))
                  ) : (
                    <Tag color="default" style={{ margin: 0 }}>
                      unassigned
                    </Tag>
                  )}
                  <Tag color="default" style={{ margin: 0 }}>
                    {podcast.total_episodes} eps
                  </Tag>
                  <UnplayedTag count={podcast.unplayed_episodes} style={{ margin: 0 }} />
                  {podcast.is_sequential && (
                    <Tag color="orange" style={{ margin: 0 }}>
                      Seq
                    </Tag>
                  )}
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
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
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
          onChange={(value) => {
            hasUserSelected.current = true;
            setViewMode(value as ViewMode);
          }}
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
            pagination={{
              pageSize: pageSize,
              showSizeChanger: true,
              pageSizeOptions: ['10', '20', '50', '100'],
              showTotal: (total, range) => `${range[0]}-${range[1]} of ${total} podcasts`,
              onShowSizeChange: (_, size) => setPageSize(size),
            }}
            size="middle"
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
              <Form.Item label="Playlists" style={{ marginBottom: 16 }}>
                <Select
                  mode="multiple"
                  value={selectedPodcast.playlist_ids}
                  onChange={(value) => {
                    handlePlaylistsChange(selectedPodcast, value);
                    setSelectedPodcast((prev) => (prev ? { ...prev, playlist_ids: value } : prev));
                  }}
                  loading={updatingId === selectedPodcast.spotify_id}
                  style={{ width: '100%' }}
                  placeholder="No playlists assigned"
                  allowClear
                  options={playlistOptions}
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
                    setSelectedPodcast((prev) =>
                      prev ? { ...prev, is_sequential: checked } : prev
                    );
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
                  Last synced:{' '}
                  {selectedPodcast.last_synced_at
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
