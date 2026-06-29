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
  Modal,
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
  confirmAccountLogin,
  accountLogout,
} from '../api/account';
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
  opening: { badge: 'processing', label: '正在打开浏览器…' },
  waiting_manual: { badge: 'warning', label: '请在浏览器窗口登录' },
  logged_in: { badge: 'success', label: '已登录' },
  failed: { badge: 'error', label: '登录失败' },
  unavailable: { badge: 'error', label: '未找到 Chrome' },
};

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);

  // --- App settings (account + scrape + engine) ---
  const [appSaving, setAppSaving] = useState(false);
  const [site, setSite] = useState('amazon.com');
  const [email, setEmail] = useState('');
  const [proxyRegion, setProxyRegion] = useState('');
  const [reviewEngine, setReviewEngine] = useState<ReviewEngine>('real_chrome');
  const [headless, setHeadless] = useState(true);
  const [maxPages, setMaxPages] = useState(3);
  const [concurrency, setConcurrency] = useState(3);
  const [codexTimeout, setCodexTimeout] = useState(600);

  // --- Account login session ---
  const [acc, setAcc] = useState<AccountStatus | null>(null);
  const [loginBusy, setLoginBusy] = useState(false);
  const [confirmBusy, setConfirmBusy] = useState(false);
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
      message.success('配置已保存');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '保存失败');
    } finally {
      setAppSaving(false);
    }
  };

  const doLogin = async () => {
    setLoginBusy(true);
    try {
      const status = await startAccountLogin();
      setAcc(status);
      message.info('正在打开浏览器窗口，请在窗口中登录…');
    } catch {
      message.error('打开登录窗口失败');
    } finally {
      setLoginBusy(false);
    }
  };

  const handleLogin = () => {
    // Remind the user to enable a US-node VPN first — otherwise Amazon geo-redirects
    // by the host IP (e.g. to the AU site) and the US account isn't recognized.
    Modal.confirm({
      title: '登录前请确认：已开启美国节点 VPN',
      content:
        '真实 Chrome 走系统网络出口。若未开美国 VPN，Amazon 会按本机 IP 把你跳到错误站点（如澳洲站 amazon.com.au），导致美国站账号无法识别、Rufus 问题也抓不到。请先在系统层开启美国节点 VPN。',
      okText: '已开启，打开浏览器登录',
      cancelText: '取消',
      onOk: doLogin,
    });
  };

  const handleConfirmLogin = async () => {
    setConfirmBusy(true);
    try {
      const status = await confirmAccountLogin();
      setAcc(status);
      if (status.state === 'logged_in') message.success('登录成功，已记住登录态');
      else message.warning('还没检测到登录，请在窗口里完成后再点');
    } catch {
      message.error('检测登录态失败');
    } finally {
      setConfirmBusy(false);
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
  const chromeUnavailable = acc?.available === false;

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', paddingTop: 24 }}>
      <Title level={3} style={{ marginBottom: 8 }}>配置中心</Title>
      <Paragraph type="secondary" style={{ marginBottom: 16 }}>
        账号登录、抓取参数与文案模型的统一配置入口。登录在打开的真实 Chrome 窗口中手动完成，登录态记在本地 Chrome 配置里，用于抓取需要登录的竞品评论 / Rufus 问题。
      </Paragraph>

      {/* --- Account & login --- */}
      <Card
        title={<Space><UserOutlined /> 账号与登录</Space>}
        extra={<Badge status={accMeta.badge} text={accMeta.label} />}
        style={{ marginBottom: 16 }}
      >
        {chromeUnavailable && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message="未找到本机 Google Chrome"
            description="登录态抓取依赖本机真实 Chrome。请先安装 Google Chrome（并执行 playwright install chrome）。"
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
            label="出口 IP / 地区"
            help="真实 Chrome 走系统网络出口。若本机 IP 被 Amazon 跳到错误站点（如跳澳洲站），请在系统层挂对应地区的 VPN（如美国）。此处暂作记录，不影响抓取。"
          >
            <Input
              placeholder="留空 / US"
              value={proxyRegion}
              onChange={(e) => setProxyRegion(e.target.value)}
              style={{ maxWidth: 360 }}
            />
          </Form.Item>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="登录方式：在真实浏览器窗口手动登录"
            description="点「打开浏览器登录」会弹出一个真实 Chrome 窗口。请你在窗口里自行登录 Amazon（含验证码 / 二次验证），完成后点「我已登录」。系统不保存你的密码，登录态记在本地 Chrome 配置里，后续抓取自动复用。"
          />
          <Space wrap>
            <Button type="primary" loading={appSaving} onClick={handleSaveApp}>
              保存配置
            </Button>
            {acc?.state !== 'waiting_manual' && (
              <Button
                icon={<LoginOutlined />}
                loading={loginBusy || acc?.state === 'opening'}
                disabled={chromeUnavailable}
                onClick={handleLogin}
              >
                {acc?.state === 'logged_in' ? '重新登录' : '打开浏览器登录'}
              </Button>
            )}
            {acc?.state === 'waiting_manual' && (
              <Button type="primary" ghost loading={confirmBusy} onClick={handleConfirmLogin}>
                我已登录
              </Button>
            )}
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
                <Radio value="real_chrome">
                  <Space>
                    <Text strong>真实 Chrome（登录态）</Text>
                    <Tag color="blue">推荐</Tag>
                    <Text type="secondary">本机真实 Chrome + 登录态抓评论/Rufus，免费、过反爬</Text>
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

    </div>
  );
}
