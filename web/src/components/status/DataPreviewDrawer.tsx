import { useState, useEffect } from 'react';
import { Drawer, Spin, Typography, Alert } from 'antd';
import { EyeOutlined } from '@ant-design/icons';
import Editor from '@monaco-editor/react';
import { getRunData } from '../../api/runs';

const { Text } = Typography;

interface Props {
  open: boolean;
  runId: string;
  dataKey: string;
  label: string;
  onClose: () => void;
}

export default function DataPreviewDrawer({ open, runId, dataKey, label, onClose }: Props) {
  const [loading, setLoading] = useState(false);
  const [content, setContent] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open || !runId || !dataKey) return;
    setLoading(true);
    setError('');
    setContent('');

    getRunData(runId, dataKey)
      .then((res) => {
        setContent(JSON.stringify(res.data, null, 2));
      })
      .catch((err) => {
        setError(err?.response?.data?.detail ?? err?.message ?? '加载失败');
      })
      .finally(() => setLoading(false));
  }, [open, runId, dataKey]);

  return (
    <Drawer
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <EyeOutlined />
          <span>{label}</span>
        </span>
      }
      width={720}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 100 }}>
          <Spin size="large" />
        </div>
      ) : error ? (
        <Alert message="加载失败" description={error} type="error" showIcon />
      ) : (
        <>
          <Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: 12 }}>
            数据键：{dataKey}
          </Text>
          <div style={{ height: 'calc(100vh - 160px)', border: '1px solid #d9d9d9', borderRadius: 6 }}>
            <Editor
              height="100%"
              defaultLanguage="json"
              value={content}
              options={{
                readOnly: true,
                minimap: { enabled: false },
                wordWrap: 'on',
                fontSize: 13,
                lineNumbers: 'on',
                scrollBeyondLastLine: false,
              }}
            />
          </div>
        </>
      )}
    </Drawer>
  );
}
