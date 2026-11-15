import { Button } from 'antd';
import { SpotifyOutlined } from '@ant-design/icons';
import { Navigate } from 'react-router';
import { useAuth, useTheme } from '../hooks';
import { LoadingSpinner } from '../components';

export function Login() {
  const { login, isAuthenticated, isLoading } = useAuth();
  const { isDarkMode } = useTheme();

  if (isLoading) {
    return <LoadingSpinner fullScreen tip="Checking authentication..." />;
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return (
    <main className="pm-login">
      <section className="pm-sheet pm-draw pm-login-sheet" aria-labelledby="login-title">
        <header className="pm-sheet-head">
          <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <img
              src={isDarkMode ? '/brand/mark-cream.svg' : '/brand/mark-ink.svg'}
              alt="Marcus Lab"
              width={28}
              height={28}
              style={{ display: 'block' }}
            />
            <span className="pm-label">Marcus Lab</span>
          </span>
        </header>
        <div className="pm-login-body">
          <h1 id="login-title" className="pm-title">
            Podcast Manager
          </h1>
          <p className="pm-login-lede">
            Automatically organize your podcast episodes into smart playlists
          </p>
          <Button
            type="primary"
            size="large"
            icon={<SpotifyOutlined />}
            onClick={login}
            block
            style={{ height: 48 }}
          >
            Log in with Spotify
          </Button>
          <p className="pm-label" style={{ margin: 0, lineHeight: 1.6 }}>
            We'll access your podcast library and create playlists on your behalf
          </p>
        </div>
      </section>
    </main>
  );
}
