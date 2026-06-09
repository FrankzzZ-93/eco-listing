import { useEffect, useState } from 'react';
import {
  Card,
  Typography,
  Radio,
  Form,
  Input,
  Button,
  Space,
  Alert,
  Tag,
  message,
  Spin,
  Divider,
} from 'antd';
import { ApiOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { getLlmSettings, updateLlmSettings, testLlmSettings } from '../api/settings';
import type { LlmProvider, LlmSettings, LlmSettingsUpdate } from '../types/settings';

const { Title, Paragraph, Text } = Typography;

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [provider, setProvider] = useState<LlmProvider>('codex-cli');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [current, setCurrent] = useState<LlmSettings | null>(null);

  const load = () => {
    setLoading(true);
    getLlmSettings()
      .then((s) => {
        setCurrent(s);
        setProvider(s.provider);
        setBaseUrl(s.base_url);
        setModel(s.model);
        setApiKey('');
      })
      .catch(() => message.error('加载模型设置失败'))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const buildPayload = (): LlmSettingsUpdate => ({
    provider,
    base_url: baseUrl.trim(),
    model: model.trim(),
    api_key: apiKey ? apiKey : undefined,
  });

  const handleSave = async () => {
    setSaving(true);
    try {
      const saved = await updateLlmSettings(buildPayload());
      setCurrent(saved);
      setApiKey('');
      message.success('设置已保存，将在下次创建的任务中生效');
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const res = await testLlmSettings(buildPayload());
      if (res.ok) message.success(res.message);
      else message.error(res.message);
    } catch {
      message.error('测试请求失败');
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}>
        <Spin size="large" />
      </div>
    );
  }

  const isApi = provider === 'openai_compatible';

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', paddingTop: 24 }}>
      <Title level={3} style={{ marginBottom: 8 }}>模型设置</Title>
      <Paragraph type="secondary" style={{ marginBottom: 16 }}>
        选择「Listing 文案撰写」使用的模型。默认使用本地 codex-cli；也可接入 OpenAI 兼容的 API
        （如中转站提供的 Opus / Claude 等模型）。此设置仅作用于文案撰写环节，其他步骤（竞品拆解、关键词分类）仍使用 codex-cli。
      </Paragraph>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 24 }}
        message="生效范围"
        description="保存后将在下次创建的任务中生效，不影响正在运行的任务。"
      />

      <Card>
        <Form layout="vertical">
          <Form.Item label="文案撰写模型">
            <Radio.Group
              value={provider}
              onChange={(e) => setProvider(e.target.value as LlmProvider)}
            >
              <Space direction="vertical">
                <Radio value="codex-cli">
                  <Space>
                    <ThunderboltOutlined />
                    <Text strong>codex-cli</Text>
                    <Tag color="default">默认</Tag>
                    <Text type="secondary">使用本地已登录的 Codex 账号，无需配置</Text>
                  </Space>
                </Radio>
                <Radio value="openai_compatible">
                  <Space>
                    <ApiOutlined />
                    <Text strong>OpenAI 兼容 API</Text>
                    <Text type="secondary">接入 Opus / Claude 等模型（支持中转站 API Key）</Text>
                  </Space>
                </Radio>
              </Space>
            </Radio.Group>
          </Form.Item>

          {isApi && (
            <>
              <Divider style={{ margin: '8px 0 20px' }} />
              <Form.Item
                label="Base URL（request path）"
                required
                help="中转站/服务的接口地址，可填写到根地址或 /v1，会自动补全为 /v1/chat/completions。例如 https://your-relay.com/v1"
              >
                <Input
                  placeholder="https://your-relay.com/v1"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
              </Form.Item>

              <Form.Item
                label="Model"
                required
                help="模型 ID，由你的服务商决定。例如 claude-opus-4-20250514、gpt-4o 等"
              >
                <Input
                  placeholder="claude-opus-4-20250514"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                />
              </Form.Item>

              <Form.Item
                label="API Key"
                required
                help={
                  current?.api_key_set
                    ? `已配置（${current.api_key_hint}）。留空则保持不变，输入则覆盖。`
                    : '中转站或服务商提供的 API Key'
                }
              >
                <Input.Password
                  placeholder={current?.api_key_set ? '保持不变' : 'sk-...'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  autoComplete="new-password"
                />
              </Form.Item>
            </>
          )}

          <Space>
            <Button type="primary" loading={saving} onClick={handleSave}>
              保存设置
            </Button>
            {isApi && (
              <Button loading={testing} onClick={handleTest} icon={<ApiOutlined />}>
                测试连接
              </Button>
            )}
          </Space>
        </Form>
      </Card>

      <Card size="small" style={{ marginTop: 16 }} title="当前生效配置">
        <Space direction="vertical" size={4}>
          <Text>
            文案撰写模型：{' '}
            <Text strong>
              {current?.provider === 'openai_compatible'
                ? `OpenAI 兼容 API（${current.model || '未设置模型'}）`
                : 'codex-cli'}
            </Text>
          </Text>
          {current?.provider === 'openai_compatible' && (
            <>
              <Text type="secondary">Base URL：{current.base_url || '未设置'}</Text>
              <Text type="secondary">
                API Key：{current.api_key_set ? current.api_key_hint : '未设置'}
              </Text>
            </>
          )}
        </Space>
      </Card>
    </div>
  );
}
