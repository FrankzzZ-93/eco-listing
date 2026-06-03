import { useState, useEffect } from 'react';
import { Card, Button, Space, Typography, Spin, message } from 'antd';
import { SaveOutlined, UndoOutlined } from '@ant-design/icons';
import Editor from '@monaco-editor/react';
import { getPrompt, updatePrompt, resetPrompt } from '../../api/prompts';
import type { PromptMeta } from '../../types/prompt';

const { Text } = Typography;

interface Props {
  prompt: PromptMeta;
  onSaved: () => void;
}

export default function PromptEditor({ prompt, onSaved }: Props) {
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLoading(true);
    getPrompt(prompt.agent, prompt.name)
      .then((data) => setContent(data.content))
      .catch(() => message.error('加载提示词失败'))
      .finally(() => setLoading(false));
  }, [prompt.agent, prompt.name]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updatePrompt(prompt.agent, prompt.name, content);
      message.success('提示词已保存');
      onSaved();
    } catch {
      message.error('保存提示词失败');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setSaving(true);
    try {
      await resetPrompt(prompt.agent, prompt.name);
      const data = await getPrompt(prompt.agent, prompt.name);
      setContent(data.content);
      message.success('已恢复默认提示词');
      onSaved();
    } catch {
      message.error('恢复失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Card style={{ height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin />
      </Card>
    );
  }

  return (
    <Card
      title={
        <Text strong>
          {prompt.agent} / {prompt.filename}
        </Text>
      }
      extra={
        <Space>
          <Button
            size="small"
            icon={<UndoOutlined />}
            onClick={handleReset}
            loading={saving}
          >
            恢复默认
          </Button>
        </Space>
      }
    >
      <div style={{ height: 400, border: '1px solid #d9d9d9', borderRadius: 6 }}>
        <Editor
          height="100%"
          defaultLanguage="markdown"
          value={content}
          onChange={(val) => setContent(val ?? '')}
          options={{
            minimap: { enabled: false },
            wordWrap: 'on',
            fontSize: 13,
            lineNumbers: 'on',
          }}
        />
      </div>
      <div style={{ marginTop: 12 }}>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          onClick={handleSave}
          loading={saving}
        >
          保存
        </Button>
        <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
          保存后将在下次创建的任务中生效
        </Text>
      </div>
    </Card>
  );
}
