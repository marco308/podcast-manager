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
} from 'antd';
import {
  PlusOutlined,
  PlayCircleOutlined,
  ThunderboltOutlined,
  DeleteOutlined,
  EditOutlined,
  SortAscendingOutlined,
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
      <List.Item>
        <div
          {...attributes}
          {...listeners}
          style={{
            cursor: 'grab',
            marginRight: 12,
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <HolderOutlined style={{ fontSize: 16, color: '#999' }} />
        </div>
        <List.Item.Meta
          title={podcast.name}
          description={
            <Text type="secondary" style={{ fontSize: 12 }}>
              {podcast.publisher}
            </Text>
          }
        />
        <InputNumber
          size="small"
          min={1}
          max={999}
          value={podcast.morning_order}
          onChange={(value) => onOrderChange(podcast.spotify_id, value)}
          placeholder="Order"
          disabled={updatingId === podcast.spotify_id}
          prefix={<SortAscendingOutlined />}
          style={{ width: 120 }}
        />
      </List.Item>
    </div>
  );
}

function MorningOrderSection() {
  const { data: newsPodcasts, isLoading } = usePodcasts('news');
  const updatePodcast = useUpdatePodcast();
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [localPodcasts, setLocalPodcasts] = useState<Podcast[]>([]);

  // Update local state when data changes
  useEffect(() => {
    if (newsPodcasts) {
      const sorted = [...newsPodcasts].sort((a, b) => {
        if (a.morning_order === null && b.morning_order === null) {
          return a.name.localeCompare(b.name);
        }
        if (a.morning_order === null) return 1;
        if (b.morning_order === null) return -1;
        return a.morning_order - b.morning_order;
      });
      setLocalPodcasts(sorted);
    }
  }, [newsPodcasts]);

  const sensors = useSensors(
    useSensor(PointerSensor),
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

    // Update morning_order for all affected podcasts
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
            data: { morning_order: update.order },
          })
        )
      );

      message.success('Order updated');
    } catch {
      message.error('Failed to update order');
      // Revert on error
      if (newsPodcasts) {
        setLocalPodcasts(newsPodcasts);
      }
    }
  };

  const handleOrderChange = async (spotifyId: string, order: number | null) => {
    setUpdatingId(spotifyId);
    try {
      await updatePodcast.mutateAsync({ spotifyId, data: { morning_order: order } });
      message.success('Morning order updated');
    } catch {
      message.error('Failed to update order');
    } finally {
      setUpdatingId(null);
    }
  };

  if (isLoading) {
    return <LoadingSpinner tip="Loading news podcasts..." />;
  }

  if (!newsPodcasts || newsPodcasts.length === 0) {
    return (
      <Card title="Morning Playlist Order" style={{ marginBottom: 24 }}>
        <Text type="secondary">
          No NEWS category podcasts found. Categorize podcasts as NEWS to set morning order.
        </Text>
      </Card>
    );
  }

  return (
    <Card
      title="Morning Playlist Order"
      style={{ marginBottom: 24 }}
      extra={
        <Text type="secondary" style={{ fontSize: 12 }}>
          Drag to reorder or enter numbers manually
        </Text>
      }
    >
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

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingPlaylist, setEditingPlaylist] = useState<Playlist | null>(null);
  const [form] = Form.useForm();

  const openCreateModal = () => {
    setEditingPlaylist(null);
    form.resetFields();
    form.setFieldsValue({ is_enabled: true });
    setIsModalOpen(true);
  };

  const openEditModal = (playlist: Playlist) => {
    setEditingPlaylist(playlist);
    form.setFieldsValue({
      name: playlist.name,
      spotify_playlist_id: playlist.spotify_playlist_id,
      rule_type: playlist.rule_type,
      is_enabled: playlist.is_enabled,
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
        };
        await updatePlaylist.mutateAsync({ id: editingPlaylist.id, data: updateData });
        message.success('Playlist updated');
      } else {
        const createData: PlaylistCreate = {
          name: values.name,
          spotify_playlist_id: values.spotify_playlist_id,
          rule_type: values.rule_type,
          is_enabled: values.is_enabled,
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
    try {
      const result = await runPlaylist.mutateAsync(id);
      message.success(result.message);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'Failed to update playlist');
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
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: 'Rule Type',
      dataIndex: 'rule_type',
      key: 'rule_type',
      render: (ruleType: PlaylistRuleType) => {
        const option = ruleTypeOptions.find((o) => o.value === ruleType);
        return <Tag color={option?.color}>{option?.label || ruleType}</Tag>;
      },
    },
    {
      title: 'Spotify Playlist',
      dataIndex: 'spotify_playlist_id',
      key: 'spotify_playlist_id',
      render: (id: string | null) =>
        id ? (
          <Text code copyable style={{ fontSize: 12 }}>
            {id}
          </Text>
        ) : (
          <Text type="secondary">Not linked</Text>
        ),
    },
    {
      title: 'Enabled',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
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
      render: (date: string | null) => (
        <Text type="secondary">
          {date ? dayjs(date).fromNow() : 'Never'}
        </Text>
      ),
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={() => handleRun(record.id)}
            loading={runPlaylist.isPending}
          >
            Run
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEditModal(record)}
          />
          <Popconfirm
            title="Delete playlist"
            description="Are you sure you want to delete this playlist mapping?"
            onConfirm={() => handleDelete(record.id)}
            okText="Delete"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" icon={<DeleteOutlined />} danger />
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
      <MorningOrderSection />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={4} style={{ marginBottom: 4 }}>Playlists</Title>
          <Text type="secondary">
            Manage your automated playlist mappings
          </Text>
        </div>
        <Space>
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

      <Table
        dataSource={playlists}
        columns={columns}
        rowKey="id"
        pagination={false}
      />

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
          <Form.Item name="is_enabled" label="Enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
