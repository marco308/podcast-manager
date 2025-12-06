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
            Automatically organizes your podcast episodes into smart playlists based on your preferences.
          </Paragraph>
          <Divider style={{ margin: '12px 0' }} />
          <Paragraph style={{ marginBottom: 0 }}>
            <Text type="secondary">
              <Text strong>Primary</Text> — Your main shows, all unplayed episodes
              <br />
              <Text strong>News</Text> — Only the latest episode per show
              <br />
              <Text strong>Background</Text> — Casual listening, all unplayed
              <br />
              <Text strong>Sequential</Text> — Plays oldest unplayed first (for serialized content)
              <br />
              <Text strong>Weekend Only</Text> — Appears only on Fri/Sat/Sun and UK holidays
            </Text>
          </Paragraph>
        </Space>
      </Card>
    </div>
  );
}
