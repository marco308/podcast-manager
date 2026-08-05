import { Layout, theme } from 'antd';
import { Outlet, Navigate } from 'react-router';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { useAuth } from '../../hooks';
import { LoadingSpinner } from '../common/LoadingSpinner';

const { Content } = Layout;

export function MainLayout() {
  const { isAuthenticated, isLoading } = useAuth();
  const { token } = theme.useToken();

  if (isLoading) {
    return <LoadingSpinner fullScreen tip="Loading..." />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header />
      <Layout>
        <Sidebar />
        <Layout style={{ padding: '24px' }}>
          <Content
            style={{
              background: token.colorBgContainer,
              padding: 24,
              margin: 0,
              minHeight: 280,
              borderRadius: 8,
            }}
          >
            <Outlet />
          </Content>
        </Layout>
      </Layout>
    </Layout>
  );
}
