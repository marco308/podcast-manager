import { Typography, Card, Descriptions, Button, Space, Divider, message } from 'antd';
import { LogoutOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { useAuth } from '../hooks';

const { Title, Text, Paragraph } = Typography;

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
        <Space direction="vertical">
          <Paragraph>
            <Text strong>Podcast Manager</Text> automatically organizes your podcast episodes
            into smart playlists based on your preferences.
          </Paragraph>
          <Paragraph>
            <Text type="secondary">
              • <Text strong>Primary</Text> podcasts are your main shows
              <br />
              • <Text strong>News</Text> podcasts only include the latest episode
              <br />
              • <Text strong>Background</Text> podcasts are for casual listening
              <br />
              • <Text strong>Sequential</Text> shows play oldest unplayed first
              <br />
              • <Text strong>Weekend Only</Text> shows only appear on weekends and holidays
            </Text>
          </Paragraph>
        </Space>
      </Card>
    </div>
  );
}
