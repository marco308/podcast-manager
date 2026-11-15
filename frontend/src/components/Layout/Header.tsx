import { useState } from 'react';
import { Layout, Avatar, Dropdown, Space, Typography, Button, Drawer, Grid } from 'antd';
import {
  UserOutlined,
  LogoutOutlined,
  SunOutlined,
  MoonOutlined,
  MenuOutlined,
} from '@ant-design/icons';
import { NavMenu } from './Sidebar';
import type { MenuProps } from 'antd';
import { useAuth, useTheme } from '../../hooks';

const { Header: AntHeader } = Layout;
const { Text } = Typography;

export function Header() {
  const { user, logout } = useAuth();
  const { isDarkMode, toggleTheme } = useTheme();
  const screens = Grid.useBreakpoint();
  const isMobile = screens.md === false;
  const [navOpen, setNavOpen] = useState(false);

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
        background: 'var(--ground)',
        padding: '0 24px',
        borderBottom: '1.5px solid var(--rule)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {isMobile && (
          <Button
            type="text"
            icon={<MenuOutlined />}
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation"
            aria-expanded={navOpen}
          />
        )}
        <img
          src={isDarkMode ? '/brand/mark-cream.svg' : '/brand/mark-ink.svg'}
          alt="Marcus Lab"
          width={28}
          height={28}
          style={{ display: 'block' }}
        />
        <span
          style={{
            fontWeight: 700,
            fontSize: 15,
            letterSpacing: '0.04em',
            textTransform: 'uppercase',
          }}
        >
          Podcast Manager
        </span>
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
                <Text
                  className="header-username"
                  style={{ textTransform: 'none', letterSpacing: 0 }}
                >
                  {user.display_name || user.spotify_id}
                </Text>
              </Space>
            </Button>
          </Dropdown>
        )}
      </Space>
      <Drawer
        placement="left"
        open={navOpen}
        onClose={() => setNavOpen(false)}
        width={260}
        title="Podcast Manager"
        styles={{ body: { padding: 0 }, header: { borderBottom: '1.5px solid var(--rule)' } }}
      >
        <NavMenu onNavigate={() => setNavOpen(false)} />
      </Drawer>
    </AntHeader>
  );
}
