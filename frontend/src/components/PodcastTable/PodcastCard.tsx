import { Avatar, Card, Space, Tag, Typography } from 'antd';
import { RightOutlined } from '@ant-design/icons';
import type { Podcast } from '../../types';
import { MissingTag, UnplayedTag } from './podcastTags';

const { Text } = Typography;

interface PodcastCardProps {
  podcast: Podcast;
  getPlaylistName: (playlistId: number) => string;
  onOpen: (podcast: Podcast) => void;
}

// One podcast in the card view (the mobile default); tapping it opens the
// settings drawer.
export function PodcastCard({ podcast, getPlaylistName, onOpen }: PodcastCardProps) {
  return (
    <Card
      size="small"
      hoverable
      onClick={() => onOpen(podcast)}
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
            <MissingTag podcast={podcast} style={{ margin: 0 }} />
          </Space>
        </div>
        <RightOutlined style={{ color: '#999', fontSize: 12, flexShrink: 0 }} />
      </div>
    </Card>
  );
}
