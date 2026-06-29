import { Layout } from 'antd';
import { Outlet } from 'react-router-dom';
import AppHeader from './AppHeader';

const { Content } = Layout;

export default function AppLayout() {
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <AppHeader />
      {/* Background comes from the Layout `bodyBg` theme token. */}
      <Content style={{ padding: 24 }}>
        <Outlet />
      </Content>
    </Layout>
  );
}
