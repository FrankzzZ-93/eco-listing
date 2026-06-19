import { useState, useEffect, useMemo } from 'react';
import {
  Card,
  Form,
  Input,
  Select,
  Button,
  Upload,
  Space,
  Typography,
  message,
  Divider,
  Row,
  Col,
  Tag,
  Steps,
  Table,
  Empty,
  Progress,
  Popconfirm,
} from 'antd';
import {
  PlusOutlined,
  MinusCircleOutlined,
  InboxOutlined,
  FileTextOutlined,
  SearchOutlined,
  TagsOutlined,
  EditOutlined,
  EyeOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { SettingOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { createRun, startRun, listRuns, uploadFile, deleteRun } from '../api/runs';
import { getAccountStatus } from '../api/account';
import { isValidAsin, normalizeAsin } from '../utils/asinValidator';
import type { RunSummary } from '../types/run';
import type { AccountStatus } from '../types/settings';

const { Dragger } = Upload;
const { Title, Text, Paragraph } = Typography;

const SITES = [
  { value: 'amazon.com.au', label: 'Amazon AU (amazon.com.au)' },
  { value: 'amazon.com', label: 'Amazon US (amazon.com)' },
  { value: 'amazon.co.uk', label: 'Amazon UK (amazon.co.uk)' },
  { value: 'amazon.de', label: 'Amazon DE (amazon.de)' },
  { value: 'amazon.co.jp', label: 'Amazon JP (amazon.co.jp)' },
];

interface FormValues {
  site: string;
  product_name: string;
  competitor_asins: { asin: string }[];
}

interface FileInputProps {
  label: string;
  hint: string;
  required?: boolean;
  multiple?: boolean;
  accept?: string;
  file?: File | null;
  files?: File[];
  onFileChange?: (file: File | null) => void;
  onFilesChange?: React.Dispatch<React.SetStateAction<File[]>>;
}

function FileInput({ label, hint, required, multiple, accept, file, files, onFileChange, onFilesChange }: FileInputProps) {
  const fileList = multiple
    ? (files ?? []).map((f, i) => ({ uid: String(i), name: f.name, status: 'done' as const }))
    : file ? [{ uid: '-1', name: file.name, status: 'done' as const }] : [];

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ marginBottom: 6 }}>
        <Text strong>{label}</Text>
        {required && <Text type="danger"> *</Text>}
        {!required && <Tag style={{ marginLeft: 8 }} color="default">可选</Tag>}
        {multiple && <Tag style={{ marginLeft: 4 }} color="blue">多文件</Tag>}
      </div>
      <Dragger
        accept={accept ?? '.csv,.json,.txt,.md,.xlsx'}
        multiple={multiple}
        maxCount={multiple ? 20 : 1}
        beforeUpload={(f) => {
          // On a multi-file drop, antd calls beforeUpload once per file; use a
          // functional state update so every file accumulates (avoids the
          // stale-closure bug where only the last dropped file survives).
          if (multiple && onFilesChange) {
            onFilesChange((prev) =>
              prev.some((p) => p.name === f.name && p.size === f.size)
                ? prev
                : [...prev, f],
            );
          } else if (onFileChange) {
            onFileChange(f);
          }
          return false;
        }}
        onRemove={(removed) => {
          if (multiple && onFilesChange) {
            onFilesChange((prev) => prev.filter((f) => f.name !== removed.name));
          } else if (onFileChange) {
            onFileChange(null);
          }
        }}
        fileList={fileList}
        style={{ padding: '8px 0' }}
      >
        <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
          <InboxOutlined style={{ fontSize: 28, color: '#1677ff' }} />
        </p>
        <p className="ant-upload-text" style={{ fontSize: 13, margin: 0 }}>
          点击或拖拽文件到此处
        </p>
        <p className="ant-upload-hint" style={{ fontSize: 12 }}>
          {hint}
        </p>
      </Dragger>
    </div>
  );
}

const WORKFLOW_STEPS = [
  { title: '认知层', description: '竞品抓取 → 评论分析 → Alex 问答 → 本品属性表', icon: <SearchOutlined /> },
  { title: '语义层', description: '关键词分类建模', icon: <TagsOutlined /> },
  { title: '表达层', description: '多轮迭代生成 Listing + ST 优化', icon: <EditOutlined /> },
];

const STATUS_ICON: Record<string, React.ReactNode> = {
  pending: <LoadingOutlined style={{ color: '#8c8c8c' }} />,
  running: <LoadingOutlined style={{ color: '#1677ff' }} />,
  waiting_human: <ExclamationCircleOutlined style={{ color: '#faad14' }} />,
  paused: <ExclamationCircleOutlined style={{ color: '#8c8c8c' }} />,
  stopped: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
  completed: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  failed: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
};

const STATUS_LABEL: Record<string, string> = {
  pending: '准备中',
  running: '运行中',
  waiting_human: '等待操作',
  paused: '已暂停',
  stopped: '已停止',
  completed: '已完成',
  failed: '失败',
  unknown: '未知',
};

function ActiveRunCard({ run, onClick, onDelete }: { run: RunSummary; onClick: () => void; onDelete: () => void }) {
  const percent = run.total_steps > 0
    ? Math.round((run.completed_steps / run.total_steps) * 100)
    : 0;

  return (
    <Card
      size="small"
      hoverable
      onClick={onClick}
      style={{ marginBottom: 12, borderLeft: `3px solid ${run.status === 'waiting_human' ? '#faad14' : '#1677ff'}` }}
    >
      <Row align="middle" gutter={16}>
        <Col flex="auto">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            {STATUS_ICON[run.status] ?? STATUS_ICON.running}
            <Text strong style={{ fontSize: 14 }}>
              {run.product_name || run.run_id}
            </Text>
            <Tag color={run.status === 'waiting_human' ? 'warning' : 'processing'}>
              {STATUS_LABEL[run.status] ?? run.status}
            </Tag>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>{run.site}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>竞品 {run.competitor_asins?.length ?? 0} 个</Text>
            {run.current_step && (
              <Text style={{ fontSize: 12, color: '#1677ff' }}>
                当前：{run.current_step}
              </Text>
            )}
          </div>
        </Col>
        <Col flex="160px">
          <Progress
            percent={percent}
            size="small"
            format={() => `${run.completed_steps}/${run.total_steps}`}
            status={run.status === 'waiting_human' ? 'exception' : 'active'}
            strokeColor={run.status === 'waiting_human' ? '#faad14' : undefined}
          />
        </Col>
        <Col>
          <Space size={4}>
            <Button type="primary" size="small" ghost icon={<EyeOutlined />}>
              查看
            </Button>
            <Popconfirm
              title="删除任务"
              description="将停止并永久删除该任务，已产出数据一并清除。"
              okText="停止并删除"
              okButtonProps={{ danger: true }}
              cancelText="取消"
              onConfirm={onDelete}
            >
              <Button
                danger
                size="small"
                icon={<DeleteOutlined />}
                onClick={(e) => e.stopPropagation()}
              />
            </Popconfirm>
          </Space>
        </Col>
      </Row>
    </Card>
  );
}

export default function InputPage() {
  const [form] = Form.useForm<FormValues>();
  const [loading, setLoading] = useState(false);
  const [keywordFile, setKeywordFile] = useState<File | null>(null);
  const [competitorListingFiles, setCompetitorListingFiles] = useState<File[]>([]);
  const [competitorReviewFiles, setCompetitorReviewFiles] = useState<File[]>([]);
  const [productAttributesFile, setProductAttributesFile] = useState<File | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [accStatus, setAccStatus] = useState<AccountStatus | null>(null);
  const navigate = useNavigate();

  const fetchRuns = () => {
    setRunsLoading(true);
    listRuns()
      .then(setRuns)
      .catch(() => {})
      .finally(() => setRunsLoading(false));
  };

  useEffect(() => {
    fetchRuns();
    const timer = setInterval(fetchRuns, 5000);
    getAccountStatus().then(setAccStatus).catch(() => {});
    return () => clearInterval(timer);
  }, []);

  const { activeRuns, finishedRuns } = useMemo(() => {
    const active: RunSummary[] = [];
    const finished: RunSummary[] = [];
    for (const r of runs) {
      if (r.status === 'pending' || r.status === 'running' || r.status === 'waiting_human' || r.status === 'paused') {
        active.push(r);
      } else {
        finished.push(r);
      }
    }
    return { activeRuns: active, finishedRuns: finished };
  }, [runs]);

  const handleSubmit = async (values: FormValues) => {
    if (!keywordFile) {
      message.warning('请上传关键词词库文件');
      return;
    }

    const competitorAsins = values.competitor_asins
      .map((item) => normalizeAsin(item.asin))
      .filter(Boolean);

    if (competitorAsins.length < 1) {
      message.warning('请至少填写 1 个竞品 ASIN');
      return;
    }

    setLoading(true);
    let runId: string | null = null;
    try {
      const res = await createRun({
        product_name: values.product_name?.trim() || '',
        competitor_asins: competitorAsins,
        site: values.site,
      });
      runId = res.run_id;
    } catch {
      message.error('任务创建失败');
      setLoading(false);
      return;
    }

    // Upload sequentially (not Promise.all): each upload is a read-modify-write
    // on the same run's graph state, so concurrent uploads race and the last
    // writer clobbers the others (e.g. keyword_library getting lost).
    const uploadJobs: Array<{ file: File; kind: 'listings' | 'keywords' | 'reviews' | 'product_attributes' | 'auto' }> = [];
    if (keywordFile) uploadJobs.push({ file: keywordFile, kind: 'keywords' });
    for (const f of competitorListingFiles) uploadJobs.push({ file: f, kind: 'listings' });
    for (const f of competitorReviewFiles) uploadJobs.push({ file: f, kind: 'reviews' });
    if (productAttributesFile) uploadJobs.push({ file: productAttributesFile, kind: 'product_attributes' });

    let uploadFailed = false;
    let attrUploadError: string | null = null;
    for (const job of uploadJobs) {
      try {
        await uploadFile(runId, job.file, job.kind);
      } catch (e) {
        uploadFailed = true;
        if (job.kind === 'product_attributes') {
          const err = e as { response?: { data?: { detail?: string } } };
          attrUploadError = err?.response?.data?.detail ?? '本品属性表上传失败';
        }
      }
    }
    // The product attribute table is special: a failed upload/conversion would
    // otherwise let the run start and silently fall back to competitor-based
    // generation. Per requirement #1, do NOT start the flow in that case —
    // clean up the just-created (empty) run and ask the user to fix or remove
    // the file before retrying.
    if (attrUploadError) {
      message.error(
        `本品属性表上传/转换失败：${attrUploadError}。流程未启动，请修正或移除该文件后重试。`,
      );
      try {
        await deleteRun(runId);
      } catch {
        // best-effort cleanup; ignore
      }
      // Keep the form intact (ASINs, files) so the user can fix or remove the
      // bad attribute file and resubmit without re-entering everything.
      fetchRuns();
      setLoading(false);
      return;
    }
    if (uploadFailed) {
      message.warning('部分文件上传失败，可稍后在任务中重新上传');
    }

    try {
      await startRun(runId);
    } catch {
      message.error('任务启动失败');
      setLoading(false);
      return;
    }

    message.success('任务创建成功');
    form.resetFields();
    setKeywordFile(null);
    setCompetitorListingFiles([]);
    setCompetitorReviewFiles([]);
    setProductAttributesFile(null);
    fetchRuns();
    window.scrollTo({ top: 0, behavior: 'smooth' });
    setLoading(false);
  };

  const finishedColumns = [
    {
      title: '产品名称',
      dataIndex: 'product_name',
      key: 'product_name',
      render: (name: string, record: RunSummary) => (
        <Text>{name || record.run_id}</Text>
      ),
    },
    {
      title: '站点',
      dataIndex: 'site',
      key: 'site',
      width: 140,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => {
        const icon = STATUS_ICON[status];
        return (
          <Space size={4}>
            {icon}
            <span>{STATUS_LABEL[status] ?? status}</span>
          </Space>
        );
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (ts: string) => {
        try { return new Date(ts).toLocaleString('zh-CN'); } catch { return ts; }
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, record: RunSummary) => (
        <Space size={0}>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/run/${record.run_id}`)}>
            查看
          </Button>
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={(e) => {
              e.stopPropagation();
              deleteRun(record.run_id)
                .then(() => { message.success('已删除'); fetchRuns(); })
                .catch(() => message.error('删除失败'));
            }}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ];

  const accLoggedIn = accStatus?.state === 'logged_in';
  const accLabel = accStatus
    ? accStatus.available === false
      ? 'browser-act 未安装'
      : accLoggedIn
        ? `已登录${accStatus.account_email ? `（${accStatus.account_email}）` : ''}`
        : '未登录'
    : '检测中…';

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', paddingTop: 24 }}>
      {/* Unified config entry: account login + scrape params + model */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row align="middle" justify="space-between" gutter={16}>
          <Col flex="auto">
            <Space size={8} wrap>
              <SettingOutlined style={{ color: '#1677ff' }} />
              <Text strong>数据源 / 账号配置</Text>
              <Tag color={accLoggedIn ? 'green' : accStatus?.available === false ? 'red' : 'default'}>
                {accLabel}
              </Tag>
              <Text type="secondary" style={{ fontSize: 12 }}>
                登录账号后可抓取需要登录的竞品评论，并记住登录态
              </Text>
            </Space>
          </Col>
          <Col>
            <Button icon={<SettingOutlined />} onClick={() => navigate('/settings')}>
              前往配置中心
            </Button>
          </Col>
        </Row>
      </Card>

      {/* Active tasks - shown prominently at the top */}
      {activeRuns.length > 0 && (
        <Card style={{ marginBottom: 24 }} title={`进行中的任务（${activeRuns.length}）`}>
          {activeRuns.map((run) => (
            <ActiveRunCard
              key={run.run_id}
              run={run}
              onClick={() => navigate(`/run/${run.run_id}`)}
              onDelete={() => {
                deleteRun(run.run_id)
                  .then(() => { message.success('已删除'); fetchRuns(); })
                  .catch(() => message.error('删除失败'));
              }}
            />
          ))}
        </Card>
      )}

      {/* Create new task form */}
      <Card>
        <Title level={3} style={{ textAlign: 'center', marginBottom: 8 }}>
          Eco Listing 生成器
        </Title>
        <Paragraph type="secondary" style={{ textAlign: 'center', marginBottom: 24 }}>
          输入竞品信息和关键词词库，自动生成高质量亚马逊 Listing
        </Paragraph>

        <Steps
          size="small"
          items={WORKFLOW_STEPS}
          style={{ marginBottom: 32, padding: '0 24px' }}
        />

        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{ site: 'amazon.com', competitor_asins: [{ asin: '' }] }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="site" label="站点" rules={[{ required: true, message: '请选择站点' }]}>
                <Select options={SITES} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="product_name" label="产品名称" tooltip="给本次任务起个名字，方便辨认（选填）">
                <Input placeholder="如：无线蓝牙耳机、瑜伽垫 等" />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item label="竞品 ASIN" tooltip="输入 1~10 个竞品的 Amazon ASIN，系统将自动抓取其 Listing、评论和 Alex 问答" required>
            <Form.List
              name="competitor_asins"
              rules={[{ validator: async (_, items) => { if (!items || items.length < 1) return Promise.reject('至少需要 1 个竞品 ASIN'); } }]}
            >
              {(fields, { add, remove }, { errors }) => (
                <>
                  {fields.map((field) => (
                    <Space key={field.key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                      <Form.Item
                        {...field}
                        name={[field.name, 'asin']}
                        rules={[
                          { required: true, message: '请填写 ASIN' },
                          { validator: (_, value) => !value || isValidAsin(value) ? Promise.resolve() : Promise.reject('ASIN 格式不正确') },
                        ]}
                        style={{ marginBottom: 0 }}
                      >
                        <Input placeholder="B0XXXXXXXXXX" style={{ width: 280, textTransform: 'uppercase' }} />
                      </Form.Item>
                      {fields.length > 1 && <MinusCircleOutlined onClick={() => remove(field.name)} />}
                    </Space>
                  ))}
                  {fields.length < 10 && (
                    <Button type="dashed" onClick={() => add({ asin: '' })} icon={<PlusOutlined />} style={{ width: 280 }}>
                      添加竞品 ASIN
                    </Button>
                  )}
                  <Form.ErrorList errors={errors} />
                </>
              )}
            </Form.List>
          </Form.Item>

          <Divider orientation="left">
            <Space><FileTextOutlined /><span>上传文件</span></Space>
          </Divider>

          <Row gutter={16}>
            <Col span={12}>
              <FileInput label="关键词词库" hint="鸥鹭出单词报告等" required file={keywordFile} onFileChange={setKeywordFile} />
            </Col>
            <Col span={12}>
              <FileInput label="本品属性表" hint="仅测试用：上传则跳过竞品采集，直接审核（支持 Excel/MD/JSON，自动转换）" accept=".json,.xlsx,.md,.txt" file={productAttributesFile} onFileChange={setProductAttributesFile} />
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <FileInput label="竞品 Listing 文本" hint="不上传则自动抓取，支持多文件" multiple files={competitorListingFiles} onFilesChange={setCompetitorListingFiles} />
            </Col>
            <Col span={12}>
              <FileInput label="竞品评论" hint="不上传则自动抓取，支持多文件" multiple files={competitorReviewFiles} onFilesChange={setCompetitorReviewFiles} />
            </Col>
          </Row>

          <Form.Item style={{ textAlign: 'center', marginTop: 24 }}>
            <Button type="primary" htmlType="submit" size="large" loading={loading} style={{ width: 200 }}>
              开始生成
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {/* Finished tasks — always visible */}
      <Card style={{ marginTop: 24 }} title={`历史任务${finishedRuns.length > 0 ? `（${finishedRuns.length}）` : ''}`}>
        {finishedRuns.length > 0 ? (
          <Table
            columns={finishedColumns}
            dataSource={finishedRuns.map((r) => ({ ...r, key: r.run_id }))}
            size="small"
            pagination={finishedRuns.length > 10 ? { pageSize: 10 } : false}
            locale={{ emptyText: '暂无历史任务' }}
          />
        ) : (
          <Empty description="暂无历史任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Card>
    </div>
  );
}
