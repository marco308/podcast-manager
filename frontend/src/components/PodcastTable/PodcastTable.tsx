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
  Tooltip,
} from 'antd';
import type { TableProps } from 'antd';
import {
  RightOutlined,
  AppstoreOutlined,
  UnorderedListOutlined,
  SearchOutlined,
  UserDeleteOutlined,
  InboxOutlined,
  UndoOutlined,
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
// Limited rules never refresh it, so show its age too and grey it out once
// it's old enough that it shouldn't be read as current (issue #241).
const UNPLAYED_STALE_DAYS = 7;

function UnplayedTag({ podcast, style }: { podcast: Podcast; style?: CSSProperties }) {
  const { unplayed_episodes: count, unplayed_counted_at: countedAt } = podcast;
  if (count === null || !countedAt) {
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
  const counted = dayjs(countedAt);
  const stale = dayjs().diff(counted, 'day') >= UNPLAYED_STALE_DAYS;
  return (
    <Tag
      color={stale ? 'default' : 'blue'}
      style={style}
      title={`Counted ${counted.format('D MMM YYYY, HH:mm')} by a playlist build that read the full episode list`}
    >
      {count} unplayed · {counted.fromNow()}
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
  // Operations in flight per podcast. A count, not a single id: two rows (or
  // two controls on one row) can be busy at once, and the first to finish
  // must not clear the other's spinner.
  const [inFlight, setInFlight] = useState<ReadonlyMap<number, number>>(() => new Map());
  // The drawer tracks the podcast by id and reads it from the cached list, so
  // optimistic writes and refetches show up there as they do in the table.
  // The snapshot only covers a podcast that has just left the list.
  const [selectedSnapshot, setSelectedSnapshot] = useState<Podcast | null>(null);
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

  const selectedPodcast = selectedSnapshot
    ? (podcasts.find((p) => p.id === selectedSnapshot.id) ?? selectedSnapshot)
    : null;

  const isUpdating = (podcastId: number) => (inFlight.get(podcastId) ?? 0) > 0;

  // Run one operation on a podcast with its spinner shown for exactly as
  // long as that operation is in flight.
  const trackUpdate = async (podcastId: number, operation: () => Promise<void>) => {
    setInFlight((prev) => new Map(prev).set(podcastId, (prev.get(podcastId) ?? 0) + 1));
    try {
      await operation();
    } finally {
      setInFlight((prev) => {
        const next = new Map(prev);
        const count = (next.get(podcastId) ?? 0) - 1;
        if (count > 0) {
          next.set(podcastId, count);
        } else {
          next.delete(podcastId);
        }
        return next;
      });
    }
  };

  const openPodcastDrawer = (podcast: Podcast) => {
    setSelectedSnapshot(podcast);
    setDrawerOpen(true);
  };

  const closePodcastDrawer = () => {
    setDrawerOpen(false);
    setSelectedSnapshot(null);
  };

  // Optimistically patch one podcast in every cached list so the table and
  // drawer reflect a change immediately (and a second change diffs against
  // it instead of stale props). In-flight list fetches are cancelled first:
  // one that started before the write would otherwise land after it and put
  // the old value back.
  const patchCachedPodcast = async (podcastId: number, patch: Partial<Podcast>) => {
    await queryClient.cancelQueries({ queryKey: podcastKeys.lists() });
    queryClient.setQueriesData<Podcast[]>({ queryKey: podcastKeys.lists() }, (old) =>
      old?.map((p) => (p.id === podcastId ? { ...p, ...patch } : p))
    );
  };

  // After a failure, re-read the truth rather than restoring a snapshot: with
  // several requests in parallel, some may have succeeded, and an earlier
  // success's refetch may already hold newer data than the snapshot.
  const refetchPodcasts = () => queryClient.invalidateQueries({ queryKey: podcastKeys.lists() });

  const handlePlaylistsChange = (podcast: Podcast, newPlaylistIds: number[]) =>
    trackUpdate(podcast.id, async () => {
      const previousIds = podcast.playlist_ids;
      await patchCachedPodcast(podcast.id, { playlist_ids: newPlaylistIds });
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
        void refetchPodcasts();
        message.error('Failed to update playlist assignments');
      }
    });

  const handleSequentialChange = (podcastId: number, checked: boolean) =>
    trackUpdate(podcastId, async () => {
      await patchCachedPodcast(podcastId, { is_sequential: checked });
      try {
        await updatePodcast.mutateAsync({ podcastId, data: { is_sequential: checked } });
        message.success(checked ? 'Marked as sequential' : 'Removed sequential flag');
      } catch {
        void refetchPodcasts();
        message.error('Failed to update');
      }
    });

  // Archive hides the podcast from the app but keeps it followed on Spotify.
  // The backend drops its playlist assignments when archiving.
  const handleArchiveChange = (podcast: Podcast, archived: boolean) =>
    trackUpdate(podcast.id, async () => {
      try {
        await updatePodcast.mutateAsync({
          podcastId: podcast.id,
          data: { is_archived: archived },
        });
        message.success(archived ? `Archived "${podcast.name}"` : `Restored "${podcast.name}"`);
        closePodcastDrawer();
      } catch {
        message.error(archived ? 'Failed to archive podcast' : 'Failed to restore podcast');
      }
    });

  // Marked by the sync when the show left the Spotify library (issue #155).
  // It contributes no episodes from that moment, and the row is deleted after
  // the grace period — say so rather than letting a playlist quietly shrink
  // and a podcast later vanish (issue #240).
  const missingTag = (podcast: Podcast, style: CSSProperties = {}) =>
    podcast.missing_since ? (
      <Tooltip
        title={`Not in your Spotify library since ${dayjs(podcast.missing_since).format('D MMM YYYY')}. It contributes no episodes to playlists, and will be removed from this app if it stays away. Follow it again on Spotify to restore it.`}
      >
        <Tag color="warning" style={style}>
          Not on Spotify
        </Tag>
      </Tooltip>
    ) : null;

  const unfollowDescription = (podcast: Podcast) =>
    podcast.missing_since
      ? `"${podcast.name}" is already gone from your Spotify library. Remove it from this app too?`
      : `Are you sure you want to unfollow "${podcast.name}"? This will remove it from Spotify and delete it from this app.`;

  const archiveDescription = (podcast: Podcast) =>
    `Hide "${podcast.name}" from this app? It stays followed on Spotify` +
    (podcast.playlist_ids.length > 0
      ? ` and will be removed from ${podcast.playlist_ids.length} playlist${podcast.playlist_ids.length === 1 ? '' : 's'}.`
      : '.') +
    ' You can restore it with "Show archived".';

  const renderArchiveButton = (podcast: Podcast, block = false) =>
    podcast.is_archived ? (
      <Button
        icon={<UndoOutlined />}
        onClick={() => handleArchiveChange(podcast, false)}
        loading={isUpdating(podcast.id)}
        size={block ? 'middle' : 'small'}
        block={block}
        aria-label="Restore podcast"
      >
        {block && 'Restore to App'}
      </Button>
    ) : (
      <Popconfirm
        title="Archive podcast"
        description={archiveDescription(podcast)}
        onConfirm={() => handleArchiveChange(podcast, true)}
        okText="Archive"
        cancelText="Cancel"
      >
        <Button
          icon={<InboxOutlined />}
          loading={isUpdating(podcast.id)}
          size={block ? 'middle' : 'small'}
          block={block}
          aria-label="Archive podcast"
        >
          {block && 'Archive (keep following on Spotify)'}
        </Button>
      </Popconfirm>
    );

  const handleUnfollow = (podcastId: number, podcastName: string) =>
    trackUpdate(podcastId, async () => {
      try {
        await unfollowPodcast.mutateAsync(podcastId);
        message.success(`Unfollowed "${podcastName}"`);
        closePodcastDrawer();
      } catch {
        message.error('Failed to unfollow podcast');
      }
    });

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
            {record.is_archived && (
              <Tag color="default" style={{ marginLeft: 8 }}>
                Archived
              </Tag>
            )}
            {missingTag(record, { marginLeft: 8 })}
          </div>
        </Space>
      ),
    },
    {
      title: 'Episodes',
      key: 'episodes',
      align: 'center',
      width: 170,
      render: (_, record) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Tag color="default">{record.total_episodes} total</Tag>
          <UnplayedTag podcast={record} />
        </Space>
      ),
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
          loading={isUpdating(record.id)}
          disabled={record.is_archived}
          style={{ width: 200 }}
          placeholder={record.is_archived ? 'Archived' : 'Unassigned'}
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
          onChange={(checked) => handleSequentialChange(record.id, checked)}
          loading={isUpdating(record.id)}
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
      // Never-synced rows count as oldest, so the comparator stays
      // consistent (two nulls compare equal) in both sort directions.
      sorter: (a, b) =>
        (a.last_synced_at ? new Date(a.last_synced_at).getTime() : 0) -
        (b.last_synced_at ? new Date(b.last_synced_at).getTime() : 0),
    },
    {
      title: 'Actions',
      key: 'actions',
      align: 'center',
      width: 110,
      render: (_, record) => (
        <Space size={8}>
          <Tooltip title={record.is_archived ? 'Restore to app' : 'Archive (keep following)'}>
            <span>{renderArchiveButton(record)}</span>
          </Tooltip>
          <Popconfirm
            title={record.missing_since ? 'Remove podcast' : 'Unfollow podcast'}
            description={unfollowDescription(record)}
            onConfirm={() => handleUnfollow(record.id, record.name)}
            okText={record.missing_since ? 'Remove' : 'Unfollow'}
            cancelText="Cancel"
            okButtonProps={{ danger: true }}
          >
            <Button
              danger
              icon={<UserDeleteOutlined />}
              loading={isUpdating(record.id)}
              size="small"
              aria-label="Unfollow podcast"
            />
          </Popconfirm>
        </Space>
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
            key={podcast.id}
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
                  <UnplayedTag podcast={podcast} style={{ margin: 0 }} />
                  {podcast.is_sequential && (
                    <Tag color="orange" style={{ margin: 0 }}>
                      Seq
                    </Tag>
                  )}
                  {podcast.is_archived && (
                    <Tag color="default" style={{ margin: 0 }}>
                      Archived
                    </Tag>
                  )}
                  {missingTag(podcast, { margin: 0 })}
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
            rowKey="id"
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
                {missingTag(selectedPodcast, { marginTop: 4 })}
              </div>
            </Space>

            <Divider style={{ margin: '16px 0' }} />

            <Form layout="vertical">
              <Form.Item label="Playlists" style={{ marginBottom: 16 }}>
                <Select
                  mode="multiple"
                  value={selectedPodcast.playlist_ids}
                  onChange={(value) => handlePlaylistsChange(selectedPodcast, value)}
                  loading={isUpdating(selectedPodcast.id)}
                  disabled={selectedPodcast.is_archived}
                  style={{ width: '100%' }}
                  placeholder={
                    selectedPodcast.is_archived ? 'Restore to assign' : 'No playlists assigned'
                  }
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
                  onChange={(checked) => handleSequentialChange(selectedPodcast.id, checked)}
                  loading={isUpdating(selectedPodcast.id)}
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

              <Space direction="vertical" style={{ width: '100%' }} size={8}>
                {renderArchiveButton(selectedPodcast, true)}
                <Popconfirm
                  title={selectedPodcast.missing_since ? 'Remove podcast' : 'Unfollow podcast'}
                  description={unfollowDescription(selectedPodcast)}
                  onConfirm={() => handleUnfollow(selectedPodcast.id, selectedPodcast.name)}
                  okText={selectedPodcast.missing_since ? 'Remove' : 'Unfollow'}
                  cancelText="Cancel"
                  okButtonProps={{ danger: true }}
                >
                  <Button
                    danger
                    icon={<UserDeleteOutlined />}
                    loading={isUpdating(selectedPodcast.id)}
                    block
                  >
                    {selectedPodcast.missing_since ? 'Remove from App' : 'Unfollow on Spotify'}
                  </Button>
                </Popconfirm>
              </Space>
            </Form>
          </div>
        )}
      </Drawer>
    </>
  );
}
