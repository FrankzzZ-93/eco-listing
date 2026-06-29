import { Layout, Typography, Space, Button, theme } from 'antd';
import { RocketOutlined, SettingOutlined, ApiOutlined } from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';

const { Header } = Layout;

export default function AppHeader() {
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = theme.useToken();

  return (
    <Header
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        // bg / height / padding come from the Layout theme tokens; the sticky
        // position + elevation come from the global stylesheet.
      }}
    >
      <Space style={{ cursor: 'pointer' }} onClick={() => navigate('/new')}>
        <RocketOutlined style={{ fontSize: 20, color: token.colorPrimary }} />
        <Typography.Title level={4} style={{ margin: 0 }}>
          Eco Listing 生成器
        </Typography.Title>
      </Space>

      <Space>
        <Button
          type={location.pathname === '/settings' ? 'primary' : 'text'}
          icon={<ApiOutlined />}
          onClick={() => navigate('/settings')}
        >
          配置中心
        </Button>
        <Button
          type={location.pathname === '/prompts' ? 'primary' : 'text'}
          icon={<SettingOutlined />}
          onClick={() => navigate('/prompts')}
        >
          提示词管理
        </Button>
      </Space>
    </Header>
  );
}
