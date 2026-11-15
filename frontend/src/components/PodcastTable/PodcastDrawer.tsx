import {
  Avatar,
  Button,
  Divider,
  Drawer,
  Form,
  Popconfirm,
  Select,
  Space,
  Switch,
  Typography,
} from 'antd';
import { UserDeleteOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Podcast } from '../../types';
import { ArchiveButton } from './ArchiveButton';
import { unfollowDescription } from './podcastCopy';
import { MissingTag } from './podcastTags';

const { Text } = Typography;

interface PodcastDrawerProps {
  open: boolean;
  podcast: Podcast | null;
  onClose: () => void;
  playlistOptions: { value: number; label: string }[];
  isUpdating: (podcastId: number) => boolean;
  onPlaylistsChange: (podcast: Podcast, playlistIds: number[]) => void;
  onSequentialChange: (podcastId: number, checked: boolean) => void;
  onArchiveChange: (podcast: Podcast, archived: boolean) => void;
  onUnfollow: (podcastId: number, podcastName: string) => void;
}

// Settings for one podcast, opened from the card view.
export function PodcastDrawer({
  open,
  podcast,
  onClose,
  playlistOptions,
  isUpdating,
  onPlaylistsChange,
  onSequentialChange,
  onArchiveChange,
  onUnfollow,
}: PodcastDrawerProps) {
  return (
    <Drawer
      title="Podcast Settings"
      placement="bottom"
      onClose={onClose}
      open={open}
      height="auto"
      styles={{
        body: { paddingBottom: 24 },
      }}
    >
      {podcast && (
        <div>
          <Space style={{ marginBottom: 16 }}>
            <Avatar src={podcast.image_url} size={56} shape="square" style={{ borderRadius: 8 }}>
              {podcast.name[0]}
            </Avatar>
            <div>
              <Text strong style={{ fontSize: 16, display: 'block' }}>
                {podcast.name}
              </Text>
              <Text type="secondary">{podcast.publisher}</Text>
              <MissingTag podcast={podcast} style={{ marginTop: 4 }} />
            </div>
          </Space>

          <Divider style={{ margin: '16px 0' }} />

          <Form layout="vertical">
            <Form.Item label="Playlists" style={{ marginBottom: 16 }}>
              <Select
                mode="multiple"
                value={podcast.playlist_ids}
                onChange={(value) => onPlaylistsChange(podcast, value)}
                loading={isUpdating(podcast.id)}
                disabled={podcast.is_archived}
                style={{ width: '100%' }}
                placeholder={podcast.is_archived ? 'Restore to assign' : 'No playlists assigned'}
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
                checked={podcast.is_sequential}
                onChange={(checked) => onSequentialChange(podcast.id, checked)}
                loading={isUpdating(podcast.id)}
              />
            </Form.Item>

            <Divider style={{ margin: '16px 0' }} />

            <Space direction="vertical" size={4} style={{ marginBottom: 16 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {podcast.total_episodes} episodes
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                Last synced:{' '}
                {podcast.last_synced_at ? dayjs(podcast.last_synced_at).fromNow() : 'Never'}
              </Text>
            </Space>

            <Divider style={{ margin: '16px 0' }} />

            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <ArchiveButton
                podcast={podcast}
                block
                loading={isUpdating(podcast.id)}
                onArchiveChange={onArchiveChange}
              />
              <Popconfirm
                title={podcast.missing_since ? 'Remove podcast' : 'Unfollow podcast'}
                description={unfollowDescription(podcast)}
                onConfirm={() => onUnfollow(podcast.id, podcast.name)}
                okText={podcast.missing_since ? 'Remove' : 'Unfollow'}
                cancelText="Cancel"
                okButtonProps={{ danger: true }}
              >
                <Button danger icon={<UserDeleteOutlined />} loading={isUpdating(podcast.id)} block>
                  {podcast.missing_since ? 'Remove from App' : 'Unfollow on Spotify'}
                </Button>
              </Popconfirm>
            </Space>
          </Form>
        </div>
      )}
    </Drawer>
  );
}
