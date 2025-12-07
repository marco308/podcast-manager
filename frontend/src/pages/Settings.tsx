import { Typography, Card, Descriptions, Button, Space, Divider, message, Tag } from 'antd';
import { LogoutOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { useAuth } from '../hooks';

const { Title, Text, Paragraph } = Typography;

const APP_VERSION = '1.0.0';

export function Settings() {
  const { user, logout } = useAuth();

  const handleLogout = async () => {
    try {
      await logout();
      message.success('Logged out successfully');
    } catch {
      message.error('Failed to logout');
    }
  };

  return (
    <div>
      <Title level={4}>Settings</Title>

      <Card title="Account" style={{ marginBottom: 24 }}>
        <Descriptions column={1}>
          <Descriptions.Item label="Spotify Username">
            {user?.spotify_id || '—'}
          </Descriptions.Item>
          <Descriptions.Item label="Display Name">
            {user?.display_name || '—'}
          </Descriptions.Item>
          <Descriptions.Item label="Email">
            {user?.email || '—'}
          </Descriptions.Item>
          <Descriptions.Item label="Account Created">
            {user?.created_at ? dayjs(user.created_at).format('MMMM D, YYYY') : '—'}
          </Descriptions.Item>
        </Descriptions>
        <Divider />
        <Button icon={<LogoutOutlined />} danger onClick={handleLogout}>
          Logout
        </Button>
      </Card>

      <Card title="About">
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <Text strong style={{ fontSize: 16 }}>Podcast Manager</Text>
            <Tag color="green" style={{ marginLeft: 8 }}>v{APP_VERSION}</Tag>
          </div>
          <Paragraph style={{ marginBottom: 0 }}>
            A powerful Spotify podcast organizer that automatically creates and maintains smart playlists
            based on your listening preferences and custom rules.
          </Paragraph>

          <Divider style={{ margin: '12px 0' }}>
            <Text strong>Features</Text>
          </Divider>

          <div>
            <Text strong style={{ fontSize: 14 }}>🎯 Smart Categorization</Text>
            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
              <Text type="secondary">
                <Text strong>Primary</Text> — Your main podcasts, all unplayed episodes
                <br />
                <Text strong>News</Text> — Time-sensitive content, only the latest episode per show
                <br />
                <Text strong>Background</Text> — Casual listening content, all unplayed episodes
                <br />
                <Text strong>Morning</Text> — Custom morning routine playlists
              </Text>
            </Paragraph>
          </div>

          <div>
            <Text strong style={{ fontSize: 14 }}>⚙️ Podcast Attributes</Text>
            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
              <Text type="secondary">
                <Text strong>Sequential</Text> — Story-based podcasts always play oldest-to-newest to maintain narrative continuity
                <br />
                <Text strong>Weekend Only</Text> — Podcasts that only appear on Fri/Sat/Sun and UK public holidays
              </Text>
            </Paragraph>
          </div>

          <div>
            <Text strong style={{ fontSize: 14 }}>📋 Flexible Playlist Ordering</Text>
            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
              <Text type="secondary">
                <Text strong>Default</Text> — Category-based automatic ordering
                <br />
                <Text strong>Custom Order</Text> — Drag-and-drop podcast ordering (respects sequential constraint)
                <br />
                <Text strong>Chronological</Text> — Sort by release date (oldest or newest first)
                <br />
                <em>Note: Sequential podcasts always maintain oldest-first ordering regardless of mode</em>
              </Text>
            </Paragraph>
          </div>

          <div>
            <Text strong style={{ fontSize: 14 }}>🔄 Automation</Text>
            <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
              <Text type="secondary">
                Automatic daily syncs keep your Spotify library and playlists up to date.
                Manually trigger updates anytime for instant refresh.
              </Text>
            </Paragraph>
          </div>

          <Divider style={{ margin: '12px 0' }} />

          <Paragraph style={{ marginBottom: 0 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              Built with FastAPI, React, and Spotify Web API
            </Text>
          </Paragraph>
        </Space>
      </Card>
    </div>
  );
}
