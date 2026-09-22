import { useState } from 'react';
import { App, Typography, Button, Table, Space, Tag, Popconfirm, Alert, Grid, Tooltip } from 'antd';
import {
  PlusOutlined,
  PlayCircleOutlined,
  ThunderboltOutlined,
  DeleteOutlined,
  EditOutlined,
  ExportOutlined,
} from '@ant-design/icons';
import type { TableProps } from 'antd';
import { Link } from 'react-router';
import dayjs from 'dayjs';
import { usePlaylists, useDeletePlaylist, useRunPlaylist, useRunAllPlaylists } from '../hooks';
import { LoadingSpinner, PlaylistFormModal } from '../components';
import { getErrorMessage } from '../api';
import { arrangementLabel, ruleSummary, spotifyPlaylistUrl } from '../utils/playlistLabels';
import type { Playlist } from '../types';

const { Title, Text } = Typography;
const { useBreakpoint } = Grid;

export function Playlists() {
  const { message } = App.useApp();
  const { data: playlists, isLoading, error } = usePlaylists();
  const deletePlaylist = useDeletePlaylist();
  const runPlaylist = useRunPlaylist();
  const runAllPlaylists = useRunAllPlaylists();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingPlaylist, setEditingPlaylist] = useState<Playlist | null>(null);
  const [runningPlaylistId, setRunningPlaylistId] = useState<number | null>(null);

  const openCreateModal = () => {
    setEditingPlaylist(null);
    setIsModalOpen(true);
  };

  const openEditModal = (playlist: Playlist) => {
    setEditingPlaylist(playlist);
    setIsModalOpen(true);
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
          <Link to={`/playlists/${record.id}`}>
            <Text strong>{name}</Text>
          </Link>
          {isMobile && (
            <div style={{ marginTop: 4 }}>
              <Tag color="blue">
                {ruleSummary(record.default_episode_limit, record.default_pick_from)}
              </Tag>
              {record.is_enabled ? <Tag color="success">On</Tag> : <Tag color="default">Off</Tag>}
              {record.is_weekend_only && <Tag color="orange">Weekend</Tag>}
              {spotifyPlaylistUrl(record.spotify_playlist_id) && (
                <a
                  href={spotifyPlaylistUrl(record.spotify_playlist_id) ?? undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ fontSize: 12 }}
                >
                  Spotify <ExportOutlined />
                </a>
              )}
            </div>
          )}
        </div>
      ),
    },
    {
      title: 'Rule',
      key: 'rule',
      responsive: ['md'] as const,
      render: (_, record) => (
        <Tooltip title="Default episodes per podcast · where they are taken from">
          <Tag color={record.default_episode_limit === 0 ? 'blue' : 'green'}>
            {ruleSummary(record.default_episode_limit, record.default_pick_from)}
          </Tag>
        </Tooltip>
      ),
    },
    {
      title: 'Arrangement',
      key: 'arrangement',
      responsive: ['lg'] as const,
      render: (_, record) => <Text>{arrangementLabel(record)}</Text>,
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
      render: (id: string | null) => {
        const url = spotifyPlaylistUrl(id);
        return url ? (
          <a href={url} target="_blank" rel="noopener noreferrer">
            Open in Spotify <ExportOutlined />
          </a>
        ) : (
          <Tooltip title="Created on the first run">
            <Text type="secondary">Not created yet</Text>
          </Tooltip>
        );
      },
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

      <PlaylistFormModal
        open={isModalOpen}
        playlist={editingPlaylist}
        onClose={() => setIsModalOpen(false)}
      />
    </div>
  );
}
