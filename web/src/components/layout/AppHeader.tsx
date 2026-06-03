import { Layout, Typography, Space, Button } from 'antd';
import { RocketOutlined, SettingOutlined } from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';

const { Header } = Layout;

export default function AppHeader() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <Header
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: '#fff',
        borderBottom: '1px solid #f0f0f0',
        padding: '0 24px',
      }}
    >
      <Space
        style={{ cursor: 'pointer' }}
        onClick={() => navigate('/new')}
      >
        <RocketOutlined style={{ fontSize: 20, color: '#1677ff' }} />
        <Typography.Title level={4} style={{ margin: 0 }}>
          Eco Listing 生成器
        </Typography.Title>
      </Space>

      <Space>
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
