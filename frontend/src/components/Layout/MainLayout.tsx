import { Layout, Alert } from 'antd';
import { Outlet, Navigate } from 'react-router';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { useAuth } from '../../hooks';
import { LoadingSpinner } from '../common/LoadingSpinner';

const { Content } = Layout;

export function MainLayout() {
  const { isAuthenticated, isLoading, isError } = useAuth();

  if (isLoading) {
    return <LoadingSpinner fullScreen tip="Loading..." />;
  }

  // The auth status check failed (network blip, server error) — auth state is
  // unknown, so show a neutral error instead of bouncing a valid session to
  // the login page.
  if (isError) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          padding: 24,
        }}
      >
        <Alert
          type="error"
          message="Unable to verify your session"
          description="Please check your connection and refresh the page."
          showIcon
        />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header />
      <Layout>
        <Sidebar />
        <Layout style={{ padding: '24px 32px' }}>
          <Content
            style={{
              background: 'transparent',
              padding: '8px 16px',
              margin: 0,
              minHeight: 280,
              maxWidth: 1440,
              width: '100%',
            }}
          >
            <Outlet />
          </Content>
        </Layout>
      </Layout>
    </Layout>
  );
}
