import { Layout, Menu, Grid } from 'antd';
import {
  DashboardOutlined,
  CustomerServiceOutlined,
  UnorderedListOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router';
import type { MenuProps } from 'antd';

const { Sider } = Layout;

const menuItems: MenuProps['items'] = [
  {
    key: '/',
    icon: <DashboardOutlined />,
    label: 'Run sheet',
  },
  {
    key: '/podcasts',
    icon: <CustomerServiceOutlined />,
    label: 'Podcasts',
  },
  {
    key: '/playlists',
    icon: <UnorderedListOutlined />,
    label: 'Playlists',
  },
  {
    key: '/settings',
    icon: <SettingOutlined />,
    label: 'Settings',
  },
];

// The section links, shared by the desktop sidebar and the mobile drawer.
export function NavMenu({ onNavigate }: { onNavigate?: () => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  // Highlight the section for nested routes too (e.g. /playlists/3 -> /playlists).
  const selectedKey = `/${location.pathname.split('/')[1] ?? ''}`;

  const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
    navigate(key);
    onNavigate?.();
  };

  return (
    <Menu
      mode="inline"
      selectedKeys={[selectedKey]}
      style={{ height: '100%', borderRight: 0, background: 'transparent' }}
      items={menuItems}
      onClick={handleMenuClick}
    />
  );
}

export function Sidebar() {
  const screens = Grid.useBreakpoint();
  // Below md the header's menu button opens the same links in a drawer.
  if (screens.md === false) return null;

  return (
    <Sider
      width={200}
      style={{
        background: 'var(--ground)',
        borderRight: '1.5px solid var(--rule)',
      }}
    >
      <NavMenu />
    </Sider>
  );
}
