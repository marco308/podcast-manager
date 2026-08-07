import { useState } from 'react';
import {
  App,
  Typography,
  Button,
  Table,
  Space,
  Tag,
  Modal,
  Form,
  Input,
  Select,
  Switch,
  Popconfirm,
  Alert,
  Card,
  List,
  Grid,
  Tooltip,
  Avatar,
} from 'antd';
import {
  PlusOutlined,
  PlayCircleOutlined,
  ThunderboltOutlined,
  DeleteOutlined,
  EditOutlined,
  HolderOutlined,
  CloseOutlined,
} from '@ant-design/icons';
import type { TableProps } from 'antd';
import dayjs from 'dayjs';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useQueryClient } from '@tanstack/react-query';
import {
  playlistKeys,
  usePlaylists,
  usePlaylistPodcasts,
  useCreatePlaylist,
  useUpdatePlaylist,
  useDeletePlaylist,
  useRunPlaylist,
  useRunAllPlaylists,
  usePodcasts,
  useAddPodcastsToPlaylist,
  useRemovePodcastFromPlaylist,
  useReorderPlaylistPodcasts,
} from '../hooks';
import { LoadingSpinner } from '../components';
import { getErrorMessage } from '../api';
import type {
  Playlist,
  PlaylistCreate,
  PlaylistUpdate,
  PlaylistPodcast,
  EpisodeMode,
} from '../types';

const { Title, Text } = Typography;
const { useBreakpoint } = Grid;

const episodeModeOptions: { value: EpisodeMode; label: string }[] = [
  { value: 'all_unplayed', label: 'All Unplayed Episodes' },
  { value: 'latest_only', label: 'Latest Episode Only' },
];

interface SortableItemProps {
  podcast: PlaylistPodcast;
  onRemove: (podcastId: number) => void;
  removing: boolean;
}

function SortableItem({ podcast, onRemove, removing }: SortableItemProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: podcast.id,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style}>
      <List.Item
        style={{
          padding: '12px 0',
        }}
      >
        <div
          {...attributes}
          {...listeners}
          role="button"
          tabIndex={0}
          aria-label="Drag to reorder"
          style={{
            cursor: 'grab',
            marginRight: 12,
            display: 'flex',
            alignItems: 'center',
            padding: '8px',
            touchAction: 'none',
          }}
        >
          <HolderOutlined style={{ fontSize: 20, color: '#999' }} />
        </div>
        <List.Item.Meta
          avatar={
            podcast.image_url ? (
              <Avatar src={podcast.image_url} size={36} shape="square" style={{ borderRadius: 6 }}>
                {podcast.name[0]}
              </Avatar>
            ) : undefined
          }
          title={
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text ellipsis style={{ maxWidth: 150 }}>
                {podcast.name}
              </Text>
              {podcast.is_sequential && (
                <Tooltip title="Sequential podcast - episodes always play oldest-first">
                  <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>
                    SEQUENTIAL
                  </Tag>
                </Tooltip>
              )}
            </div>
          }
          description={
            <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
              {podcast.publisher}
            </Text>
          }
        />
        <Tooltip title="Remove from playlist">
          <Button
            size="small"
            icon={<CloseOutlined />}
            onClick={() => onRemove(podcast.id)}
            loading={removing}
            danger
            type="text"
            aria-label="Remove from playlist"
          />
        </Tooltip>
      </List.Item>
    </div>
  );
}

interface PlaylistOrderingSectionProps {
  playlist: Playlist | null;
}

function PlaylistOrderingSection({ playlist }: PlaylistOrderingSectionProps) {
  const shouldRender = playlist && playlist.ordering_mode === 'podcast_order';

  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { data: playlistPodcasts, isLoading } = usePlaylistPodcasts(playlist?.id ?? 0);
  const { data: allPodcasts } = usePodcasts();
  const addPodcasts = useAddPodcastsToPlaylist();
  const removePodcast = useRemovePodcastFromPlaylist();
  const reorderPodcasts = useReorderPlaylistPodcasts();
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [localPodcasts, setLocalPodcasts] = useState<PlaylistPodcast[]>([]);
  const [syncedPodcasts, setSyncedPodcasts] = useState<PlaylistPodcast[] | undefined>(undefined);

  // Sync the local (drag-reorderable) copy whenever the server data changes.
  // Adjusting state during render is React's recommended alternative to a
  // state-setting effect (the query keeps a stable reference between refetches).
  if (playlistPodcasts && playlistPodcasts !== syncedPodcasts) {
    setSyncedPodcasts(playlistPodcasts);
    setLocalPodcasts(
      [...playlistPodcasts].sort((a, b) => {
        if (a.position === null && b.position === null) {
          return a.name.localeCompare(b.name);
        }
        if (a.position === null) return 1;
        if (b.position === null) return -1;
        return a.position - b.position;
      })
    );
  }

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 200,
        tolerance: 5,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  if (!shouldRender) return null;

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;

    if (!over || active.id === over.id) {
      return;
    }

    const oldIndex = localPodcasts.findIndex((p) => p.id === active.id);
    const newIndex = localPodcasts.findIndex((p) => p.id === over.id);

    const newOrder = arrayMove(localPodcasts, oldIndex, newIndex);
    setLocalPodcasts(newOrder);

    try {
      await reorderPodcasts.mutateAsync({
        playlistId: playlist.id,
        podcastIds: newOrder.map((p) => p.id),
      });
      message.success('Order updated');
    } catch {
      message.error('Failed to update order');
      // Refetch the authoritative order rather than snapping back to the last
      // fetched snapshot, which may predate a reorder that already committed.
      // Clearing the sync marker makes the render-time sync block re-run even
      // if the refetch returns referentially identical data.
      setSyncedPodcasts(undefined);
      queryClient.invalidateQueries({ queryKey: playlistKeys.podcasts(playlist.id) });
    }
  };

  const handleRemove = async (podcastId: number) => {
    setRemovingId(podcastId);
    try {
      await removePodcast.mutateAsync({ playlistId: playlist.id, podcastId });
      message.success('Podcast removed from playlist');
    } catch {
      message.error('Failed to remove podcast');
    } finally {
      setRemovingId(null);
    }
  };

  const handleAddPodcast = async (podcastId: number) => {
    try {
      await addPodcasts.mutateAsync({
        playlistId: playlist.id,
        podcastIds: [podcastId],
      });
      message.success('Podcast added to playlist');
    } catch {
      message.error('Failed to add podcast');
    }
  };

  if (isLoading) {
    return <LoadingSpinner tip="Loading podcasts..." />;
  }

  // Get podcast IDs already in the playlist
  const assignedIds = new Set(localPodcasts.map((p) => p.id));
  const availablePodcasts = (allPodcasts || []).filter((p) => !assignedIds.has(p.id));

  const hasSequentialPodcasts = localPodcasts.some((p) => p.is_sequential);

  return (
    <Card
      title={`${playlist.name} - Podcast Order`}
      style={{ marginBottom: 24 }}
      extra={
        <Text type="secondary" style={{ fontSize: 12 }}>
          Drag to reorder
        </Text>
      }
    >
      {/* Add podcast selector */}
      {availablePodcasts.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Select<number>
            showSearch
            style={{ width: '100%', maxWidth: 400 }}
            placeholder="Add a podcast to this playlist..."
            filterOption={(input, option) =>
              String(option?.label ?? '')
                .toLowerCase()
                .includes(input.toLowerCase())
            }
            onSelect={(value: number) => handleAddPodcast(value)}
            value={undefined}
            options={availablePodcasts.map((p) => ({
              value: p.id,
              label: p.name,
            }))}
          />
        </div>
      )}

      {hasSequentialPodcasts && (
        <Alert
          type="info"
          message="Sequential podcasts detected"
          description="Podcasts marked as sequential (story-based) will always play oldest-to-newest regardless of ordering."
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {localPodcasts.length === 0 ? (
        <Text type="secondary">
          No podcasts assigned to this playlist yet. Use the selector above to add podcasts.
        </Text>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext
            items={localPodcasts.map((p) => p.id)}
            strategy={verticalListSortingStrategy}
          >
            <List
              dataSource={localPodcasts}
              renderItem={(podcast) => (
                <SortableItem
                  key={podcast.id}
                  podcast={podcast}
                  onRemove={handleRemove}
                  removing={removingId === podcast.id}
                />
              )}
            />
          </SortableContext>
        </DndContext>
      )}
    </Card>
  );
}

export function Playlists() {
  const { message } = App.useApp();
  const { data: playlists, isLoading, error } = usePlaylists();
  const createPlaylist = useCreatePlaylist();
  const updatePlaylist = useUpdatePlaylist();
  const deletePlaylist = useDeletePlaylist();
  const runPlaylist = useRunPlaylist();
  const runAllPlaylists = useRunAllPlaylists();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingPlaylist, setEditingPlaylist] = useState<Playlist | null>(null);
  const [selectedOrderingPlaylist, setSelectedOrderingPlaylist] = useState<Playlist | null>(null);
  const [runningPlaylistId, setRunningPlaylistId] = useState<number | null>(null);
  const [form] = Form.useForm();

  // Keep the ordering selection reconciled with fresh playlist data on every
  // render (React's recommended alternative to a state-setting effect; React
  // Query's structural sharing keeps references stable when data is unchanged):
  // clear the selection if the playlist was deleted or left podcast_order mode,
  // refresh the object reference when the playlist changed, and otherwise
  // auto-select the first podcast_order playlist.
  if (playlists) {
    if (selectedOrderingPlaylist) {
      const fresh = playlists.find((p) => p.id === selectedOrderingPlaylist.id);
      if (!fresh || fresh.ordering_mode !== 'podcast_order') {
        setSelectedOrderingPlaylist(null);
      } else if (fresh !== selectedOrderingPlaylist) {
        setSelectedOrderingPlaylist(fresh);
      }
    } else {
      const podcastOrderPlaylist = playlists.find((p) => p.ordering_mode === 'podcast_order');
      if (podcastOrderPlaylist) {
        setSelectedOrderingPlaylist(podcastOrderPlaylist);
      }
    }
  }

  const openCreateModal = () => {
    setEditingPlaylist(null);
    form.resetFields();
    form.setFieldsValue({
      is_enabled: true,
      ordering_mode: 'default',
      episode_mode: 'all_unplayed',
      is_weekend_only: false,
    });
    setIsModalOpen(true);
  };

  const openEditModal = (playlist: Playlist) => {
    setEditingPlaylist(playlist);
    form.setFieldsValue({
      name: playlist.name,
      spotify_playlist_id: playlist.spotify_playlist_id,
      episode_mode: playlist.episode_mode,
      is_enabled: playlist.is_enabled,
      is_weekend_only: playlist.is_weekend_only,
      ordering_mode: playlist.ordering_mode || 'default',
    });
    setIsModalOpen(true);
  };

  const handleSubmit = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      // Form validation error — Ant Design shows inline errors automatically
      return;
    }

    try {
      if (editingPlaylist) {
        const updateData: PlaylistUpdate = {
          name: values.name,
          spotify_playlist_id: values.spotify_playlist_id,
          is_enabled: values.is_enabled,
          episode_mode: values.episode_mode,
          is_weekend_only: values.is_weekend_only,
          ordering_mode: values.ordering_mode,
        };
        await updatePlaylist.mutateAsync({ id: editingPlaylist.id, data: updateData });
        message.success('Playlist updated');
      } else {
        const createData: PlaylistCreate = {
          name: values.name,
          spotify_playlist_id: values.spotify_playlist_id,
          episode_mode: values.episode_mode,
          is_enabled: values.is_enabled,
          is_weekend_only: values.is_weekend_only,
          ordering_mode: values.ordering_mode || 'default',
        };
        await createPlaylist.mutateAsync(createData);
        message.success('Playlist created');
      }
      setIsModalOpen(false);
    } catch {
      message.error('Failed to save playlist');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deletePlaylist.mutateAsync(id);
      message.success('Playlist deleted');
    } catch {
      message.error('Failed to delete playlist');
    }
  };

  const handleRun = async (id: number) => {
    setRunningPlaylistId(id);
    try {
      const result = await runPlaylist.mutateAsync(id);
      // A skipped weekend-only playlist and a partial rebuild both come back
      // 200, but neither is a clean success — don't report them as one.
      if (result.skipped || result.partial) {
        message.warning(result.message);
      } else {
        message.success(result.message);
      }
    } catch (err: unknown) {
      message.error(getErrorMessage(err));
    } finally {
      setRunningPlaylistId(null);
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

  const columns: TableProps<Playlist>['columns'] = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: Playlist) => (
        <div>
          <Text strong>{name}</Text>
          {isMobile && (
            <div style={{ marginTop: 4 }}>
              <Tag color={record.episode_mode === 'all_unplayed' ? 'blue' : 'green'}>
                {record.episode_mode === 'all_unplayed' ? 'All Unplayed' : 'Latest Only'}
              </Tag>
              {record.is_enabled ? <Tag color="success">On</Tag> : <Tag color="default">Off</Tag>}
              {record.is_weekend_only && <Tag color="orange">Weekend</Tag>}
            </div>
          )}
        </div>
      ),
    },
    {
      title: 'Episode Mode',
      dataIndex: 'episode_mode',
      key: 'episode_mode',
      responsive: ['md'] as const,
      render: (mode: EpisodeMode) => {
        const option = episodeModeOptions.find((o) => o.value === mode);
        return (
          <Tag color={mode === 'all_unplayed' ? 'blue' : 'green'}>{option?.label || mode}</Tag>
        );
      },
    },
    {
      title: 'Podcasts',
      dataIndex: 'podcast_count',
      key: 'podcast_count',
      responsive: ['md'] as const,
      align: 'center',
      width: 100,
      render: (count: number) => <Text>{count}</Text>,
    },
    {
      title: 'Spotify Playlist',
      dataIndex: 'spotify_playlist_id',
      key: 'spotify_playlist_id',
      responsive: ['lg'] as const,
      render: (id: string | null) =>
        id ? (
          <a
            href={`https://open.spotify.com/playlist/${id}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open in Spotify
          </a>
        ) : (
          <Text type="secondary">Not linked</Text>
        ),
    },
    {
      title: 'Enabled',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      responsive: ['md'] as const,
      render: (enabled: boolean, record: Playlist) => (
        <Space size={4}>
          {enabled ? <Tag color="success">Enabled</Tag> : <Tag color="default">Disabled</Tag>}
          {record.is_weekend_only && <Tag color="orange">Weekend</Tag>}
        </Space>
      ),
    },
    {
      title: 'Last Updated',
      dataIndex: 'last_updated_at',
      key: 'last_updated_at',
      responsive: ['xl'] as const,
      render: (date: string | null) => (
        <Text type="secondary">{date ? dayjs(date).fromNow() : 'Never'}</Text>
      ),
    },
    {
      title: 'Actions',
      key: 'actions',
      width: isMobile ? 100 : undefined,
      render: (_, record) => (
        <Space size={isMobile ? 4 : 8}>
          <Tooltip title="Run playlist">
            <Button
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => handleRun(record.id)}
              loading={runningPlaylistId === record.id}
            >
              {!isMobile && 'Run'}
            </Button>
          </Tooltip>
          <Tooltip title="Edit">
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => openEditModal(record)}
              aria-label="Edit playlist"
            />
          </Tooltip>
          <Popconfirm
            title="Delete playlist"
            description="Are you sure you want to delete this playlist mapping?"
            onConfirm={() => handleDelete(record.id)}
            okText="Delete"
            okButtonProps={{ danger: true }}
          >
            <Tooltip title="Delete">
              <Button size="small" icon={<DeleteOutlined />} danger aria-label="Delete playlist" />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (isLoading) {
    return <LoadingSpinner tip="Loading playlists..." />;
  }

  if (error) {
    return (
      <Alert
        type="error"
        message="Failed to load playlists"
        description="Please try refreshing the page."
        showIcon
      />
    );
  }

  return (
    <div>
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
            Playlists
          </Title>
          <Text type="secondary">Manage your automated playlist mappings</Text>
        </div>
        <div>
          <Space wrap>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={handleRunAll}
              loading={runAllPlaylists.isPending}
            >
              Update All
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
              Add Playlist
            </Button>
          </Space>
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <Table dataSource={playlists} columns={columns} rowKey="id" pagination={false} />
      </div>

      {playlists && playlists.some((p) => p.ordering_mode === 'podcast_order') && (
        <Card style={{ marginBottom: 24, marginTop: 24 }}>
          <div style={{ marginBottom: 16 }}>
            <Text strong>Playlist Custom Ordering</Text>
            <div style={{ marginTop: 8 }}>
              <Select
                style={{ width: '100%', maxWidth: 400 }}
                placeholder="Select a playlist to configure ordering"
                value={selectedOrderingPlaylist?.id}
                onChange={(playlistId) => {
                  const playlist = playlists.find((p) => p.id === playlistId);
                  setSelectedOrderingPlaylist(playlist || null);
                }}
                options={playlists
                  .filter((p) => p.ordering_mode === 'podcast_order')
                  .map((p) => ({
                    value: p.id,
                    label: p.name,
                  }))}
              />
            </div>
          </div>
        </Card>
      )}

      <PlaylistOrderingSection playlist={selectedOrderingPlaylist} />

      <Modal
        title={editingPlaylist ? 'Edit Playlist' : 'Add Playlist'}
        open={isModalOpen}
        onOk={handleSubmit}
        onCancel={() => setIsModalOpen(false)}
        confirmLoading={createPlaylist.isPending || updatePlaylist.isPending}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="Name"
            rules={[{ required: true, message: 'Please enter a name' }]}
          >
            <Input placeholder="e.g., Morning Podcasts" />
          </Form.Item>
          <Form.Item
            name="episode_mode"
            label="Episode Mode"
            rules={[{ required: true, message: 'Please select an episode mode' }]}
          >
            <Select
              placeholder="Select episode mode"
              options={episodeModeOptions.map((opt) => ({
                value: opt.value,
                label: opt.label,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="spotify_playlist_id"
            label="Spotify Playlist ID"
            extra="The ID of an existing Spotify playlist to update, or leave blank to create a new one"
          >
            <Input placeholder="e.g., 37i9dQZF1DX..." />
          </Form.Item>
          <Form.Item
            name="ordering_mode"
            label="Ordering Mode"
            extra="How should episodes be ordered in this playlist?"
          >
            <Select
              placeholder="Select ordering mode"
              options={[
                {
                  value: 'default',
                  label: (
                    <div>
                      <div>Default</div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        Use standard sorting
                      </Text>
                    </div>
                  ),
                },
                {
                  value: 'podcast_order',
                  label: (
                    <div>
                      <div>Custom podcast order</div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        Manually order podcasts (sequential podcasts always oldest-first)
                      </Text>
                    </div>
                  ),
                },
                {
                  value: 'chronological_asc',
                  label: (
                    <div>
                      <div>Oldest first</div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        Sort episodes by release date (oldest first)
                      </Text>
                    </div>
                  ),
                },
                {
                  value: 'chronological_desc',
                  label: (
                    <div>
                      <div>Newest first</div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        Sort episodes by release date (newest first for non-sequential podcasts)
                      </Text>
                    </div>
                  ),
                },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="is_weekend_only"
            label="Weekend Only"
            valuePropName="checked"
            extra="Only update this playlist on weekends and UK public holidays"
          >
            <Switch />
          </Form.Item>
          <Form.Item name="is_enabled" label="Enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
