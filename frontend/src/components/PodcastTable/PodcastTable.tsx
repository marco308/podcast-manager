import { useState } from 'react';
import { Table, Avatar, Switch, message, Typography, Space, Tag } from 'antd';
import type { TableProps } from 'antd';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import type { Podcast, PodcastCategory } from '../../types';
import { CategorySelect } from './CategorySelect';
import { useUpdatePodcast } from '../../hooks';

dayjs.extend(relativeTime);

const { Text } = Typography;

interface PodcastTableProps {
  podcasts: Podcast[];
  loading?: boolean;
}

export function PodcastTable({ podcasts, loading }: PodcastTableProps) {
  const updatePodcast = useUpdatePodcast();
  const [updatingId, setUpdatingId] = useState<string | null>(null);

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

  const columns: TableProps<Podcast>['columns'] = [
    {
      title: 'Podcast',
      key: 'podcast',
      width: 400,
      render: (_, record) => (
        <Space>
          <Avatar
            src={record.image_url}
            size={48}
            shape="square"
            style={{ borderRadius: 8 }}
          >
            {record.name[0]}
          </Avatar>
          <div>
            <Text strong style={{ display: 'block' }}>
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
      dataIndex: 'total_episodes',
      key: 'total_episodes',
      width: 100,
      align: 'center',
      render: (count: number) => (
        <Tag color="default">{count}</Tag>
      ),
    },
    {
      title: 'Category',
      key: 'category',
      width: 140,
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
      width: 100,
      align: 'center',
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
      width: 120,
      align: 'center',
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
      width: 140,
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
  ];

  return (
    <Table
      dataSource={podcasts}
      columns={columns}
      rowKey="spotify_id"
      loading={loading}
      pagination={{
        pageSize: 20,
        showSizeChanger: true,
        showTotal: (total, range) => `${range[0]}-${range[1]} of ${total} podcasts`,
      }}
      size="middle"
      rowClassName={(record) => {
        return record.category !== 'none' ? `category-${record.category}` : '';
      }}
    />
  );
}
