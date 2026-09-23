import { Layout, Avatar, Dropdown, Space, Typography, Button, theme } from 'antd';
import { UserOutlined, LogoutOutlined, SunOutlined, MoonOutlined } from '@ant-design/icons';
import type { MenuProps } from 'antd';
import { useAuth, useTheme } from '../../hooks';

const { Header: AntHeader } = Layout;
const { Text } = Typography;

export function Header() {
  const { user, logout } = useAuth();
  const { isDarkMode, toggleTheme } = useTheme();
  const { token } = theme.useToken();

  const menuItems: MenuProps['items'] = [
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: 'Logout',
      onClick: () => logout(),
    },
  ];

  return (
    <AntHeader
      className="app-header"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: token.colorBgContainer,
        padding: '0 24px',
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 24 }}>🎧</span>
        <Text strong style={{ fontSize: 18 }}>
          Podcast Manager
        </Text>
      </div>

      <Space>
        <Button
          type="text"
          icon={isDarkMode ? <SunOutlined /> : <MoonOutlined />}
          onClick={toggleTheme}
          aria-label={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
        />
        {user && (
          <Dropdown menu={{ items: menuItems }} placement="bottomRight" trigger={['click']}>
            {/* A real button so the menu is reachable by keyboard (Tab, then
                Enter/Space) and announced as one; hover-only on a Space was
                mouse-only. */}
            <Button
              type="text"
              aria-label={`Account menu for ${user.display_name || user.spotify_id}`}
              aria-haspopup="menu"
              style={{ height: 'auto', padding: '4px 8px' }}
            >
              <Space>
                <Avatar icon={<UserOutlined />} />
                <Text className="header-username">{user.display_name || user.spotify_id}</Text>
              </Space>
            </Button>
          </Dropdown>
        )}
      </Space>
    </AntHeader>
  );
}
