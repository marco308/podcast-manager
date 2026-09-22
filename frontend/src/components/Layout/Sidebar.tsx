import { Layout, Menu, theme } from 'antd';
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
    label: 'Dashboard',
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

export function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = theme.useToken();
  // Highlight the section for nested routes too (e.g. /playlists/3 -> /playlists).
  const selectedKey = `/${location.pathname.split('/')[1] ?? ''}`;

  const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
    navigate(key);
  };

  return (
    <Sider
      width={200}
      breakpoint="md"
      collapsedWidth={0}
      style={{
        background: token.colorBgContainer,
        borderRight: `1px solid ${token.colorBorderSecondary}`,
      }}
    >
      <Menu
        mode="inline"
        selectedKeys={[selectedKey]}
        style={{ height: '100%', borderRight: 0 }}
        items={menuItems}
        onClick={handleMenuClick}
      />
    </Sider>
  );
}
