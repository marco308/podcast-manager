import { Button, Card, Typography, Space } from 'antd';
import { SpotifyOutlined } from '@ant-design/icons';
import { Navigate } from 'react-router';
import { useAuth } from '../hooks';
import { LoadingSpinner } from '../components';

const { Title, Text } = Typography;

export function Login() {
  const { login, isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <LoadingSpinner fullScreen tip="Checking authentication..." />;
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)',
      }}
    >
      <Card
        style={{
          width: '100%',
          maxWidth: 400,
          margin: '0 16px',
          textAlign: 'center',
          borderRadius: 16,
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.2)',
        }}
      >
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div style={{ fontSize: 64 }}>🎧</div>
          <Title level={2} style={{ marginBottom: 0 }}>
            Podcast Manager
          </Title>
          <Text type="secondary">
            Automatically organize your podcast episodes into smart playlists
          </Text>
          <Button
            type="primary"
            size="large"
            icon={<SpotifyOutlined />}
            onClick={login}
            style={{
              width: '100%',
              height: 48,
              background: '#1DB954',
              borderColor: '#1DB954',
              borderRadius: 24,
            }}
          >
            Login with Spotify
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            We'll access your podcast library and create playlists on your behalf
          </Text>
        </Space>
      </Card>
    </div>
  );
}
