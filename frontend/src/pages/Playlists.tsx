import { useState, useEffect } from 'react';
import {
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
  message,
  Popconfirm,
  Alert,
  Card,
  List,
  InputNumber,
  Grid,
  Tooltip,
} from 'antd';
import {
  PlusOutlined,
  PlayCircleOutlined,
  ThunderboltOutlined,
  DeleteOutlined,
  EditOutlined,
  HolderOutlined,
} from '@ant-design/icons';
import type { TableProps } from 'antd';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
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
import {
  usePlaylists,
  useCreatePlaylist,
  useUpdatePlaylist,
  useDeletePlaylist,
  useRunPlaylist,
  useRunAllPlaylists,
  usePodcasts,
  useUpdatePodcast,
} from '../hooks';
import { LoadingSpinner } from '../components';
import type { Playlist, PlaylistRuleType, PlaylistCreate, PlaylistUpdate, Podcast } from '../types';

dayjs.extend(relativeTime);

const { Title, Text } = Typography;
const { useBreakpoint } = Grid;

const ruleTypeOptions: { value: PlaylistRuleType; label: string; color: string }[] = [
  { value: 'primary', label: 'Primary', color: 'blue' },
  { value: 'news', label: 'News', color: 'green' },
  { value: 'morning', label: 'Morning', color: 'orange' },
  { value: 'background', label: 'Background', color: 'purple' },
];

interface SortableItemProps {
  podcast: Podcast;
  onOrderChange: (spotifyId: string, order: number | null) => void;
  updatingId: string | null;
}

function SortableItem({ podcast, onOrderChange, updatingId }: SortableItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: podcast.spotify_id });

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
          touchAction: 'none',
        }}
      >
        <div
          {...attributes}
          {...listeners}
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
          title={
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text ellipsis style={{ maxWidth: 150 }}>{podcast.name}</Text>
              {podcast.is_sequential && (
                <Tooltip title="Sequential podcast - episodes always play oldest-first">
                  <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>SEQUENTIAL</Tag>
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
        <InputNumber
          size="small"
          min={1}
          max={999}
          value={podcast.playlist_order || podcast.morning_order}
          onChange={(value) => onOrderChange(podcast.spotify_id, value)}
          placeholder="#"
          disabled={updatingId === podcast.spotify_id}
          style={{ width: 70 }}
        />
      </List.Item>
    </div>
  );
}

interface PlaylistOrderingSectionProps {
  playlist: Playlist | null;
}

function PlaylistOrderingSection({ playlist }: PlaylistOrderingSectionProps) {
  // Only show if playlist exists and has custom ordering mode
  if (!playlist || playlist.ordering_mode !== 'podcast_order') {
    return null;
  }

  // Map rule_type to category for fetching podcasts
  const categoryMap: Record<PlaylistRuleType, string> = {
    primary: 'primary',
    news: 'news',
    morning: 'news', // Morning playlists use NEWS category podcasts
    background: 'background',
  };

  const category = categoryMap[playlist.rule_type] as 'primary' | 'news' | 'background' | 'none';

  const { data: podcasts, isLoading } = usePodcasts(category);
  const updatePodcast = useUpdatePodcast();
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [localPodcasts, setLocalPodcasts] = useState<Podcast[]>([]);

  // Update local state when data changes
  useEffect(() => {
    if (podcasts) {
      const sorted = [...podcasts].sort((a, b) => {
        const aOrder = a.playlist_order ?? a.morning_order;
        const bOrder = b.playlist_order ?? b.morning_order;
        if (aOrder === null && bOrder === null) {
          return a.name.localeCompare(b.name);
        }
        if (aOrder === null) return 1;
        if (bOrder === null) return -1;
        return aOrder - bOrder;
      });
      setLocalPodcasts(sorted);
    }
  }, [podcasts]);

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

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;

    if (!over || active.id === over.id) {
      return;
    }

    const oldIndex = localPodcasts.findIndex((p) => p.spotify_id === active.id);
    const newIndex = localPodcasts.findIndex((p) => p.spotify_id === over.id);

    const newOrder = arrayMove(localPodcasts, oldIndex, newIndex);
    setLocalPodcasts(newOrder);

    // Update playlist_order for all affected podcasts
    try {
      const updates = newOrder.map((podcast, index) => ({
        spotifyId: podcast.spotify_id,
        order: index + 1,
      }));

      // Batch update all podcasts
      await Promise.all(
        updates.map((update) =>
          updatePodcast.mutateAsync({
            spotifyId: update.spotifyId,
            data: { playlist_order: update.order },
          })
        )
      );

      message.success('Order updated');
    } catch {
      message.error('Failed to update order');
      // Revert on error
      if (podcasts) {
        setLocalPodcasts(podcasts);
      }
    }
  };

  const handleOrderChange = async (spotifyId: string, order: number | null) => {
    setUpdatingId(spotifyId);
    try {
      await updatePodcast.mutateAsync({ spotifyId, data: { playlist_order: order } });
      message.success('Playlist order updated');
    } catch {
      message.error('Failed to update order');
    } finally {
      setUpdatingId(null);
    }
  };

  if (isLoading) {
    return <LoadingSpinner tip="Loading podcasts..." />;
  }

  if (!podcasts || podcasts.length === 0) {
    const categoryLabel = category.toUpperCase();
    return (
      <Card title={`${playlist.name} - Podcast Order`} style={{ marginBottom: 24 }}>
        <Text type="secondary">
          No {categoryLabel} category podcasts found. Categorize podcasts as {categoryLabel} to set order.
        </Text>
      </Card>
    );
  }

  const hasSequentialPodcasts = podcasts.some(p => p.is_sequential);

  return (
    <Card
      title={`${playlist.name} - Podcast Order`}
      style={{ marginBottom: 24 }}
      extra={
        <Text type="secondary" style={{ fontSize: 12 }}>
          Drag to reorder or enter numbers manually
        </Text>
      }
    >
      {hasSequentialPodcasts && (
        <Alert
          type="info"
          message="Sequential podcasts detected"
          description="Podcasts marked as sequential (story-based) will always play oldest-to-newest regardless of ordering."
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={localPodcasts.map((p) => p.spotify_id)}
          strategy={verticalListSortingStrategy}
        >
          <List
            dataSource={localPodcasts}
            renderItem={(podcast) => (
              <SortableItem
                key={podcast.spotify_id}
                podcast={podcast}
                onOrderChange={handleOrderChange}
                updatingId={updatingId}
              />
            )}
          />
        </SortableContext>
      </DndContext>
    </Card>
  );
}

export function Playlists() {
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

  // Automatically select the first playlist with podcast_order mode when playlists load
  useEffect(() => {
    if (playlists && !selectedOrderingPlaylist) {
      const podcastOrderPlaylist = playlists.find(p => p.ordering_mode === 'podcast_order');
      if (podcastOrderPlaylist) {
        setSelectedOrderingPlaylist(podcastOrderPlaylist);
      }
    }
  }, [playlists, selectedOrderingPlaylist]);

  const openCreateModal = () => {
    setEditingPlaylist(null);
    form.resetFields();
    form.setFieldsValue({ is_enabled: true, ordering_mode: 'default' });
    setIsModalOpen(true);
  };

  const openEditModal = (playlist: Playlist) => {
    setEditingPlaylist(playlist);
    form.setFieldsValue({
      name: playlist.name,
      spotify_playlist_id: playlist.spotify_playlist_id,
      rule_type: playlist.rule_type,
      is_enabled: playlist.is_enabled,
      ordering_mode: playlist.ordering_mode || 'default',
    });
    setIsModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (editingPlaylist) {
        const updateData: PlaylistUpdate = {
          name: values.name,
          spotify_playlist_id: values.spotify_playlist_id,
          is_enabled: values.is_enabled,
          ordering_mode: values.ordering_mode,
        };
        await updatePlaylist.mutateAsync({ id: editingPlaylist.id, data: updateData });
        message.success('Playlist updated');
      } else {
        const createData: PlaylistCreate = {
          name: values.name,
          spotify_playlist_id: values.spotify_playlist_id,
          rule_type: values.rule_type,
          is_enabled: values.is_enabled,
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
      message.success(result.message);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Failed to update playlist');
    } finally {
      setRunningPlaylistId(null);
    }
  };

  const handleRunAll = async () => {
    try {
      const result = await runAllPlaylists.mutateAsync();
      message.success(result.message);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Failed to update playlists');
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
              <Tag color={ruleTypeOptions.find((o) => o.value === record.rule_type)?.color}>
                {ruleTypeOptions.find((o) => o.value === record.rule_type)?.label}
              </Tag>
              {record.is_enabled ? (
                <Tag color="success">On</Tag>
              ) : (
                <Tag color="default">Off</Tag>
              )}
            </div>
          )}
        </div>
      ),
    },
    {
      title: 'Rule Type',
      dataIndex: 'rule_type',
      key: 'rule_type',
      responsive: ['md'] as const,
      render: (ruleType: PlaylistRuleType) => {
        const option = ruleTypeOptions.find((o) => o.value === ruleType);
        return <Tag color={option?.color}>{option?.label || ruleType}</Tag>;
      },
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
      render: (enabled: boolean) =>
        enabled ? (
          <Tag color="success">Enabled</Tag>
        ) : (
          <Tag color="default">Disabled</Tag>
        ),
    },
    {
      title: 'Last Updated',
      dataIndex: 'last_updated_at',
      key: 'last_updated_at',
      responsive: ['xl'] as const,
      render: (date: string | null) => (
        <Text type="secondary">
          {date ? dayjs(date).fromNow() : 'Never'}
        </Text>
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
              <Button size="small" icon={<DeleteOutlined />} danger />
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <Title level={4} style={{ marginBottom: 4 }}>Playlists</Title>
          <Text type="secondary">
            Manage your automated playlist mappings
          </Text>
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
        <Table
          dataSource={playlists}
          columns={columns}
          rowKey="id"
          pagination={false}
        />
      </div>

      {playlists && playlists.some(p => p.ordering_mode === 'podcast_order') && (
        <Card style={{ marginBottom: 24, marginTop: 24 }}>
          <div style={{ marginBottom: 16 }}>
            <Text strong>Playlist Custom Ordering</Text>
            <div style={{ marginTop: 8 }}>
              <Select
                style={{ width: '100%', maxWidth: 400 }}
                placeholder="Select a playlist to configure ordering"
                value={selectedOrderingPlaylist?.id}
                onChange={(playlistId) => {
                  const playlist = playlists.find(p => p.id === playlistId);
                  setSelectedOrderingPlaylist(playlist || null);
                }}
                options={playlists
                  .filter(p => p.ordering_mode === 'podcast_order')
                  .map(p => ({
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
            name="rule_type"
            label="Rule Type"
            rules={[{ required: !editingPlaylist, message: 'Please select a rule type' }]}
          >
            <Select
              placeholder="Select rule type"
              disabled={!!editingPlaylist}
              options={ruleTypeOptions.map((opt) => ({
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
                  label: <div>
                    <div>Default (by category)</div>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      Use standard sorting for this category
                    </Text>
                  </div>
                },
                {
                  value: 'podcast_order',
                  label: <div>
                    <div>Custom podcast order</div>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      Manually order podcasts (sequential podcasts always oldest-first)
                    </Text>
                  </div>
                },
                {
                  value: 'chronological_asc',
                  label: <div>
                    <div>Oldest first</div>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      Sort episodes by release date (oldest first)
                    </Text>
                  </div>
                },
                {
                  value: 'chronological_desc',
                  label: <div>
                    <div>Newest first</div>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      Sort episodes by release date (newest first for non-sequential podcasts)
                    </Text>
                  </div>
                },
              ]}
            />
          </Form.Item>
          <Form.Item name="is_enabled" label="Enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
