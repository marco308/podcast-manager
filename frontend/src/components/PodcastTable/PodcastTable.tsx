import { useState, useEffect, useMemo, useRef } from 'react';
import {
  Table,
  Avatar,
  Switch,
  Typography,
  Space,
  Tag,
  Grid,
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
  AppstoreOutlined,
  UnorderedListOutlined,
  SearchOutlined,
  UserDeleteOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Podcast } from '../../types';
import { usePlaylists } from '../../hooks';
import { ArchiveButton } from './ArchiveButton';
import { PodcastCard } from './PodcastCard';
import { PodcastDrawer } from './PodcastDrawer';
import { unfollowDescription } from './podcastCopy';
import { MissingTag, UnplayedTag } from './podcastTags';
import { usePodcastAssignments } from './usePodcastAssignments';

const { useBreakpoint } = Grid;
const { Text } = Typography;

interface PodcastTableProps {
  podcasts: Podcast[];
}

type ViewMode = 'cards' | 'table';

export function PodcastTable({ podcasts }: PodcastTableProps) {
  const { data: playlists } = usePlaylists();
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

  const openPodcastDrawer = (podcast: Podcast) => {
    setSelectedSnapshot(podcast);
    setDrawerOpen(true);
  };

  const closePodcastDrawer = () => {
    setDrawerOpen(false);
    setSelectedSnapshot(null);
  };

  const {
    isUpdating,
    handlePlaylistsChange,
    handleSequentialChange,
    handleArchiveChange,
    handleUnfollow,
  } = usePodcastAssignments({ onLeft: closePodcastDrawer });

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
            <MissingTag podcast={record} style={{ marginLeft: 8 }} />
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
            <span>
              <ArchiveButton
                podcast={record}
                loading={isUpdating(record.id)}
                onArchiveChange={handleArchiveChange}
              />
            </span>
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
          <PodcastCard
            key={podcast.id}
            podcast={podcast}
            getPlaylistName={getPlaylistName}
            onOpen={openPodcastDrawer}
          />
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
      <PodcastDrawer
        open={drawerOpen}
        podcast={selectedPodcast}
        onClose={closePodcastDrawer}
        playlistOptions={playlistOptions}
        isUpdating={isUpdating}
        onPlaylistsChange={handlePlaylistsChange}
        onSequentialChange={handleSequentialChange}
        onArchiveChange={handleArchiveChange}
        onUnfollow={handleUnfollow}
      />
    </>
  );
}
