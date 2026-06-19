import { useEffect, useRef, useState } from 'react';
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
  Select,
  Switch,
  InputNumber,
  Badge,
} from 'antd';
import {
  ApiOutlined,
  ThunderboltOutlined,
  UserOutlined,
  LoginOutlined,
  LogoutOutlined,
  CloudDownloadOutlined,
} from '@ant-design/icons';
import {
  getLlmSettings,
  updateLlmSettings,
  testLlmSettings,
  getAppSettings,
  updateAppSettings,
} from '../api/settings';
import {
  getAccountStatus,
  startAccountLogin,
  submitAccountCaptcha,
  accountLogout,
} from '../api/account';
import CaptchaModal from '../components/common/CaptchaModal';
import type {
  LlmProvider,
  LlmSettings,
  LlmSettingsUpdate,
  AppSettings,
  ReviewEngine,
  AccountStatus,
} from '../types/settings';

const { Title, Paragraph, Text } = Typography;

const SITES = [
  { value: 'amazon.com', label: 'Amazon US (amazon.com)' },
  { value: 'amazon.com.au', label: 'Amazon AU (amazon.com.au)' },
  { value: 'amazon.co.uk', label: 'Amazon UK (amazon.co.uk)' },
  { value: 'amazon.de', label: 'Amazon DE (amazon.de)' },
  { value: 'amazon.co.jp', label: 'Amazon JP (amazon.co.jp)' },
];

const ACCOUNT_STATE_META: Record<
  AccountStatus['state'],
  { badge: 'default' | 'processing' | 'warning' | 'success' | 'error'; label: string }
> = {
  idle: { badge: 'default', label: '未登录' },
  logging_in: { badge: 'processing', label: '登录中…' },
  waiting_captcha: { badge: 'warning', label: '等待人机验证' },
  logged_in: { badge: 'success', label: '已登录' },
  failed: { badge: 'error', label: '登录失败' },
  unavailable: { badge: 'error', label: 'browser-act 未安装' },
};

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);

  // --- App settings (account + scrape + engine) ---
  const [appSaving, setAppSaving] = useState(false);
  const [site, setSite] = useState('amazon.com');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordSet, setPasswordSet] = useState(false);
  const [proxyRegion, setProxyRegion] = useState('');
  const [reviewEngine, setReviewEngine] = useState<ReviewEngine>('browser_act');
  const [headless, setHeadless] = useState(true);
  const [maxPages, setMaxPages] = useState(3);
  const [concurrency, setConcurrency] = useState(3);
  const [codexTimeout, setCodexTimeout] = useState(600);

  // --- Account login session ---
  const [acc, setAcc] = useState<AccountStatus | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);
  const [captchaLoading, setCaptchaLoading] = useState(false);
  const pollRef = useRef<number | null>(null);

  // --- LLM settings ---
  const [llmSaving, setLlmSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [provider, setProvider] = useState<LlmProvider>('codex-cli');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [currentLlm, setCurrentLlm] = useState<LlmSettings | null>(null);

  const applyAppSettings = (s: AppSettings) => {
    setSite(s.account.site);
    setEmail(s.account.email);
    setPasswordSet(s.account.password_set);
    setProxyRegion(s.account.proxy_region ?? '');
    setReviewEngine(s.review_engine);
    setHeadless(s.scrape.browser_headless);
    setMaxPages(s.scrape.scrape_max_review_pages);
    setConcurrency(s.scrape.research_concurrency);
    setCodexTimeout(s.scrape.codex_timeout);
  };

  useEffect(() => {
    Promise.all([getAppSettings(), getLlmSettings()])
      .then(([app, llm]) => {
        applyAppSettings(app);
        setCurrentLlm(llm);
        setProvider(llm.provider);
        setBaseUrl(llm.base_url);
        setModel(llm.model);
      })
      .catch(() => message.error('加载配置失败'))
      .finally(() => setLoading(false));

    // Initial probe (detect an already-remembered session), then poll.
    getAccountStatus(true).then(setAcc).catch(() => {});
    pollRef.current = window.setInterval(() => {
      getAccountStatus().then(setAcc).catch(() => {});
    }, 3000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  const handleSaveApp = async () => {
    setAppSaving(true);
    try {
      const saved = await updateAppSettings({
        account: {
          site,
          email: email.trim(),
          password: password ? password : undefined,
          proxy_region: proxyRegion.trim(),
        },
        scrape: {
          browser_headless: headless,
          scrape_max_review_pages: maxPages,
          research_concurrency: concurrency,
          codex_timeout: codexTimeout,
        },
        review_engine: reviewEngine,
      });
      applyAppSettings(saved);
      setPassword('');
      message.success('配置已保存');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '保存失败');
    } finally {
      setAppSaving(false);
    }
  };

  const handleLogin = async () => {
    setLoginBusy(true);
    try {
      const status = await startAccountLogin();
      setAcc(status);
      message.info('已开始登录，请稍候…');
    } catch {
      message.error('启动登录失败');
    } finally {
      setLoginBusy(false);
    }
  };

  const handleLogout = async () => {
    try {
      const status = await accountLogout();
      setAcc(status);
      message.success('已退出会话');
    } catch {
      message.error('退出失败');
    }
  };

  const handleAccountCaptcha = async (answer: string) => {
    setCaptchaLoading(true);
    try {
      const status = await submitAccountCaptcha(answer);
      setAcc(status);
    } catch {
      message.error('提交验证失败');
    } finally {
      setCaptchaLoading(false);
    }
  };

  const buildLlmPayload = (): LlmSettingsUpdate => ({
    provider,
    base_url: baseUrl.trim(),
    model: model.trim(),
    api_key: apiKey ? apiKey : undefined,
  });

  const handleSaveLlm = async () => {
    setLlmSaving(true);
    try {
      const saved = await updateLlmSettings(buildLlmPayload());
      setCurrentLlm(saved);
      setApiKey('');
      message.success('模型设置已保存，将在下次创建的任务中生效');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '保存失败');
    } finally {
      setLlmSaving(false);
    }
  };

  const handleTestLlm = async () => {
    setTesting(true);
    try {
      const res = await testLlmSettings(buildLlmPayload());
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
  const accMeta = acc ? ACCOUNT_STATE_META[acc.state] : ACCOUNT_STATE_META.idle;
  const browserActUnavailable = acc?.available === false;

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', paddingTop: 24 }}>
      <Title level={3} style={{ marginBottom: 8 }}>配置中心</Title>
      <Paragraph type="secondary" style={{ marginBottom: 16 }}>
        账号登录、抓取参数与文案模型的统一配置入口。账号登录后会记住登录态，用于通过 browser-act 抓取需要登录的竞品评论。
      </Paragraph>

      {/* --- Account & login --- */}
      <Card
        title={<Space><UserOutlined /> 账号与登录</Space>}
        extra={<Badge status={accMeta.badge} text={accMeta.label} />}
        style={{ marginBottom: 16 }}
      >
        {browserActUnavailable && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message="browser-act 未安装"
            description="登录态抓取依赖 browser-act CLI。请先安装：uv tool install browser-act-cli --python 3.12"
          />
        )}
        <Form layout="vertical">
          <Form.Item label="抓取站点">
            <Select value={site} onChange={setSite} options={SITES} style={{ maxWidth: 360 }} />
          </Form.Item>
          <Form.Item label="账号邮箱 / 手机号">
            <Input
              placeholder="amazon@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{ maxWidth: 360 }}
              autoComplete="username"
            />
          </Form.Item>
          <Form.Item
            label="账号密码"
            help={passwordSet ? '已保存密码。留空则保持不变，输入则覆盖。' : '用于自动填充登录表单，本地保存'}
          >
            <Input.Password
              placeholder={passwordSet ? '保持不变' : '••••••••'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{ maxWidth: 360 }}
              autoComplete="new-password"
            />
          </Form.Item>
          <Form.Item
            label="代理地区"
            help="本机出口 IP 若被 Amazon 跳转到错误站点，可填地区码（如 US）让 stealth 浏览器从该国出口。留空则用本机 IP。"
          >
            <Input
              placeholder="留空 / US"
              value={proxyRegion}
              onChange={(e) => setProxyRegion(e.target.value)}
              style={{ maxWidth: 360 }}
            />
          </Form.Item>
          <Space wrap>
            <Button type="primary" loading={appSaving} onClick={handleSaveApp}>
              保存配置
            </Button>
            <Button
              icon={<LoginOutlined />}
              loading={loginBusy || acc?.state === 'logging_in'}
              disabled={browserActUnavailable}
              onClick={handleLogin}
            >
              {acc?.state === 'logged_in' ? '重新登录' : '登录并记住登录态'}
            </Button>
            {acc?.state === 'logged_in' && (
              <Button icon={<LogoutOutlined />} onClick={handleLogout}>
                退出会话
              </Button>
            )}
          </Space>
          {acc?.message && (
            <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              {acc.message}
            </Paragraph>
          )}
        </Form>
      </Card>

      {/* --- Scrape settings --- */}
      <Card
        title={<Space><CloudDownloadOutlined /> 抓取设置</Space>}
        style={{ marginBottom: 16 }}
      >
        <Form layout="vertical">
          <Form.Item label="评论抓取引擎">
            <Radio.Group value={reviewEngine} onChange={(e) => setReviewEngine(e.target.value as ReviewEngine)}>
              <Space direction="vertical">
                <Radio value="browser_act">
                  <Space>
                    <Text strong>browser-act（登录态）</Text>
                    <Tag color="blue">推荐</Tag>
                    <Text type="secondary">使用已登录账号抓取评论，遇验证码弹窗输入</Text>
                  </Space>
                </Radio>
                <Radio value="builtin">
                  <Space>
                    <Text strong>内置引擎</Text>
                    <Text type="secondary">Playwright + Codex CLI 降级方案，无需登录</Text>
                  </Space>
                </Radio>
              </Space>
            </Radio.Group>
          </Form.Item>
          <Space size="large" wrap>
            <Form.Item label="评论抓取页数" tooltip="每个竞品最多抓取的评论页数">
              <InputNumber min={1} max={20} value={maxPages} onChange={(v) => setMaxPages(v ?? 3)} />
            </Form.Item>
            <Form.Item label="并发抓取数" tooltip="同时抓取的竞品数量">
              <InputNumber min={1} max={10} value={concurrency} onChange={(v) => setConcurrency(v ?? 3)} />
            </Form.Item>
            <Form.Item label="Codex 超时（秒）">
              <InputNumber min={30} max={3600} value={codexTimeout} onChange={(v) => setCodexTimeout(v ?? 600)} />
            </Form.Item>
            <Form.Item label="无头模式" tooltip="关闭后浏览器窗口可见，便于人工排查">
              <Switch checked={headless} onChange={setHeadless} />
            </Form.Item>
          </Space>
          <div>
            <Button type="primary" loading={appSaving} onClick={handleSaveApp}>
              保存配置
            </Button>
          </div>
        </Form>
      </Card>

      {/* --- LLM / model settings --- */}
      <Card title={<Space><ThunderboltOutlined /> 模型设置</Space>} style={{ marginBottom: 16 }}>
        <Paragraph type="secondary">
          选择「Listing 文案撰写」使用的模型。默认使用本地 codex-cli；也可接入 OpenAI 兼容的 API。此设置仅作用于文案撰写环节。
        </Paragraph>
        <Form layout="vertical">
          <Form.Item label="文案撰写模型">
            <Radio.Group value={provider} onChange={(e) => setProvider(e.target.value as LlmProvider)}>
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
                help="中转站/服务的接口地址，可填写到根地址或 /v1，会自动补全。例如 https://your-relay.com/v1"
              >
                <Input placeholder="https://your-relay.com/v1" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
              </Form.Item>
              <Form.Item label="Model" required help="模型 ID，由你的服务商决定。例如 claude-opus-4-20250514、gpt-4o 等">
                <Input placeholder="claude-opus-4-20250514" value={model} onChange={(e) => setModel(e.target.value)} />
              </Form.Item>
              <Form.Item
                label="API Key"
                required
                help={
                  currentLlm?.api_key_set
                    ? `已配置（${currentLlm.api_key_hint}）。留空则保持不变，输入则覆盖。`
                    : '中转站或服务商提供的 API Key'
                }
              >
                <Input.Password
                  placeholder={currentLlm?.api_key_set ? '保持不变' : 'sk-...'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  autoComplete="new-password"
                />
              </Form.Item>
            </>
          )}

          <Space>
            <Button type="primary" loading={llmSaving} onClick={handleSaveLlm}>
              保存模型设置
            </Button>
            {isApi && (
              <Button loading={testing} onClick={handleTestLlm} icon={<ApiOutlined />}>
                测试连接
              </Button>
            )}
          </Space>
        </Form>
      </Card>

      <CaptchaModal
        open={acc?.state === 'waiting_captcha'}
        title="登录人机验证"
        message={acc?.message}
        imageUrl={acc?.image_url}
        loading={captchaLoading}
        onSubmit={handleAccountCaptcha}
      />
    </div>
  );
}
