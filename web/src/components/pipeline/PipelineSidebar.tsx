import { useState } from 'react';
import { Steps, Typography, Tag, Button, Space, Drawer, message, Tooltip } from 'antd';
import {
  LoadingOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  FileTextOutlined,
  EditOutlined,
  EyeOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import Editor from '@monaco-editor/react';
import { getPrompt, updatePrompt } from '../../api/prompts';
import DataPreviewDrawer from '../status/DataPreviewDrawer';
import type { RunDetail } from '../../types/run';

const { Text } = Typography;

const sidebarStyles = `
@keyframes step-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
@keyframes step-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(22,119,255,0.4); }
  50% { box-shadow: 0 0 0 5px rgba(22,119,255,0); }
}
.step-running-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  animation: step-pulse 2s ease-in-out infinite;
}
.step-running-wrap .anticon {
  animation: step-spin 1.2s linear infinite;
  font-size: 16px;
  color: #1677ff;
}
`;

type StepStatus = 'running' | 'completed' | 'waiting' | 'pending' | 'error';

interface PromptRef {
  agent: string;
  name: string;
  label: string;
}

interface DataRef {
  key: string;
  label: string;
}

interface PipelineStep {
  key: string;
  title: string;
  status: StepStatus;
  description?: string;
  prompts: PromptRef[];
  dataRefs: DataRef[];
}

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '准备中' },
  running: { color: 'processing', text: '运行中' },
  waiting_human: { color: 'warning', text: '等待操作' },
  paused: { color: 'default', text: '已暂停' },
  stopped: { color: 'error', text: '已停止' },
  completed: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
};

function getStepIcon(status: StepStatus) {
  switch (status) {
    case 'running':
      return (
        <span className="step-running-wrap">
          <LoadingOutlined />
        </span>
      );
    case 'completed':
      return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    case 'waiting':
      return <ExclamationCircleOutlined style={{ color: '#faad14' }} />;
    case 'error':
      return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    default:
      return <ClockCircleOutlined style={{ color: '#d9d9d9' }} />;
  }
}

function computeSteps(run: RunDetail | undefined): PipelineStep[] {
  if (!run) {
    return defaultSteps();
  }

  const { memory_snapshot: mem, status, pending_action } = run;
  const isRunning = status === 'running';

  type StepDef = {
    key: string;
    title: string;
    completedKey: string;
    runningDesc: string;
    completedDesc?: string;
    prompts: PromptRef[];
    dataRefs: DataRef[];
    overrideStatus?: StepStatus;
    overrideDesc?: string;
  };

  const defs: StepDef[] = [
    {
      key: 'research',
      title: '竞品数据采集',
      completedKey: 'has_competitor_listings',
      runningDesc: '正在抓取竞品信息…',
      completedDesc: '数据已采集',
      prompts: [{ agent: 'research', name: 'rufus_extract_v1', label: 'Rufus 问题提取' }],
      dataRefs: [
        { key: 'competitor_listings', label: '竞品 Listing' },
        { key: 'customer_reviews', label: '竞品评论' },
        { key: 'rufus_questions', label: 'Rufus 问答' },
      ],
    },
    {
      key: 'product_analyst',
      title: '产品属性分析',
      completedKey: 'has_product_attributes_draft',
      runningDesc: '正在生成属性表…',
      prompts: [
        { agent: 'product_analyst', name: 'info_fusion_v2', label: '信息融合分析' },
        { agent: 'product_analyst', name: 'self_eval_v2', label: '自我评估' },
      ],
      dataRefs: [{ key: 'product_attributes_draft', label: '属性表初稿' }],
    },
    {
      key: 'review',
      title: '人工审核',
      completedKey: 'has_approved_product_attributes',
      runningDesc: '',
      prompts: [],
      dataRefs: [{ key: 'approved_product_attributes', label: '已审核属性表' }],
      overrideStatus: pending_action?.type === 'review_product_attributes' ? 'waiting' : undefined,
      overrideDesc: pending_action?.type === 'review_product_attributes' ? '请审核产品属性表' : undefined,
    },
    {
      key: 'keyword_review',
      title: '关键词审核',
      completedKey: 'has_keywords_reviewed',
      runningDesc: '',
      prompts: [],
      dataRefs: [{ key: 'keyword_library', label: '关键词词库' }],
      overrideStatus: pending_action?.type === 'review_keywords' ? 'waiting' : undefined,
      overrideDesc: pending_action?.type === 'review_keywords' ? '请审核关键词词库' : undefined,
    },
    {
      key: 'keyword_strategist',
      title: '关键词分类',
      completedKey: 'has_classified_keywords',
      runningDesc: '正在分类关键词…',
      prompts: [{ agent: 'keyword_strategist', name: 'classify_v2', label: '关键词分类' }],
      dataRefs: [{ key: 'classified_keywords', label: '分类关键词' }],
    },
    {
      key: 'copywriter',
      title: 'Listing 文案生成',
      completedKey: 'has_final_listing',
      runningDesc: '多轮迭代撰写中…',
      prompts: [
        { agent: 'copywriter', name: 'round_1_draft_v2', label: 'R1 初稿' },
        { agent: 'copywriter', name: 'round_2_rufus_v2', label: 'R2 Rufus 优化' },
        { agent: 'copywriter', name: 'round_3_compliance_v2', label: 'R3 合规校正' },
      ],
      dataRefs: [{ key: 'final_listing', label: '最终 Listing' }],
    },
    {
      key: 'st_optimization',
      title: 'ST 词频优化',
      completedKey: 'has_final_st',
      runningDesc: '正在优化搜索词…',
      completedDesc: '优化完成',
      prompts: [],
      dataRefs: [{ key: 'final_st', label: '最终 ST' }],
    },
  ];

  let foundRunning = false;
  const steps: PipelineStep[] = defs.map((def) => {
    const completed = !!(mem as unknown as Record<string, boolean> | undefined)?.[def.completedKey];

    if (def.overrideStatus && !completed) {
      foundRunning = true;
      return {
        key: def.key, title: def.title, prompts: def.prompts, dataRefs: def.dataRefs,
        status: def.overrideStatus,
        description: def.overrideDesc,
      };
    }

    if (completed) {
      return {
        key: def.key, title: def.title, prompts: def.prompts, dataRefs: def.dataRefs,
        status: 'completed' as StepStatus,
        description: def.completedDesc,
      };
    }

    if (isRunning && !foundRunning) {
      foundRunning = true;
      return {
        key: def.key, title: def.title, prompts: def.prompts, dataRefs: def.dataRefs,
        status: 'running' as StepStatus,
        description: def.runningDesc || undefined,
      };
    }

    return {
      key: def.key, title: def.title, prompts: def.prompts, dataRefs: def.dataRefs,
      status: 'pending' as StepStatus,
    };
  });

  if (status === 'failed') {
    const idx = steps.findIndex((s) => s.status === 'running');
    if (idx >= 0) {
      steps[idx].status = 'error';
      steps[idx].description = '执行出错';
    }
  }

  return steps;
}

function defaultSteps(): PipelineStep[] {
  return [
    { key: 'research', title: '竞品数据采集', status: 'pending', prompts: [{ agent: 'research', name: 'rufus_extract_v1', label: 'Rufus 问题提取' }], dataRefs: [] },
    { key: 'product_analyst', title: '产品属性分析', status: 'pending', prompts: [{ agent: 'product_analyst', name: 'info_fusion_v2', label: '信息融合分析' }, { agent: 'product_analyst', name: 'self_eval_v2', label: '自我评估' }], dataRefs: [] },
    { key: 'review', title: '人工审核', status: 'pending', prompts: [], dataRefs: [] },
    { key: 'keyword_review', title: '关键词审核', status: 'pending', prompts: [], dataRefs: [] },
    { key: 'keyword_strategist', title: '关键词分类', status: 'pending', prompts: [{ agent: 'keyword_strategist', name: 'classify_v2', label: '关键词分类' }], dataRefs: [] },
    { key: 'copywriter', title: 'Listing 文案生成', status: 'pending', prompts: [{ agent: 'copywriter', name: 'round_1_draft_v2', label: 'R1 初稿' }, { agent: 'copywriter', name: 'round_2_rufus_v2', label: 'R2 Rufus 优化' }, { agent: 'copywriter', name: 'round_3_compliance_v2', label: 'R3 合规校正' }], dataRefs: [] },
    { key: 'st_optimization', title: 'ST 词频优化', status: 'pending', prompts: [], dataRefs: [] },
  ];
}

interface Props {
  run: RunDetail | undefined;
  runId: string | undefined;
}

export default function PipelineSidebar({ run, runId }: Props) {
  const steps = computeSteps(run);
  const statusInfo = run ? STATUS_TAG[run.status] : undefined;

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingPrompt, setEditingPrompt] = useState<PromptRef | null>(null);
  const [promptContent, setPromptContent] = useState('');
  const [promptLoading, setPromptLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const [dataDrawer, setDataDrawer] = useState<{ open: boolean; key: string; label: string }>({
    open: false, key: '', label: '',
  });

  const handleOpenPrompt = async (ref: PromptRef) => {
    setEditingPrompt(ref);
    setDrawerOpen(true);
    setPromptLoading(true);
    try {
      const data = await getPrompt(ref.agent, ref.name);
      setPromptContent(data.content);
    } catch {
      message.error('加载提示词失败');
      setPromptContent('');
    } finally {
      setPromptLoading(false);
    }
  };

  const handleSave = async () => {
    if (!editingPrompt) return;
    setSaving(true);
    try {
      await updatePrompt(editingPrompt.agent, editingPrompt.name, promptContent);
      message.success('提示词已保存，下次执行生效');
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveAndRerun = async () => {
    if (!editingPrompt || !runId) return;
    setSaving(true);
    try {
      await updatePrompt(editingPrompt.agent, editingPrompt.name, promptContent);
      message.success('提示词已保存。从当前步骤重跑功能即将上线');
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: '16px 12px' }}>
      <style>{sidebarStyles}</style>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Text strong>流程进度</Text>
        {statusInfo && <Tag color={statusInfo.color}>{statusInfo.text}</Tag>}
      </div>
      <Steps
        direction="vertical"
        size="small"
        items={steps.map((step) => ({
          title: <Text style={{ fontSize: 13 }}>{step.title}</Text>,
          description: (
            <div>
              {step.description && (
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                  {step.description}
                </Text>
              )}
              {step.prompts.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                  {step.prompts.map((p) => (
                    <Tooltip key={`${p.agent}/${p.name}`} title="查看 / 编辑提示词">
                      <Tag
                        icon={<FileTextOutlined />}
                        style={{ cursor: 'pointer', fontSize: 11 }}
                        onClick={() => handleOpenPrompt(p)}
                      >
                        {p.label}
                      </Tag>
                    </Tooltip>
                  ))}
                </div>
              )}
              {step.status === 'completed' && step.dataRefs.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                  {step.dataRefs.map((d) => (
                    <Tooltip key={d.key} title="查看产出数据">
                      <Tag
                        icon={<EyeOutlined />}
                        color="green"
                        style={{ cursor: 'pointer', fontSize: 11 }}
                        onClick={() => setDataDrawer({ open: true, key: d.key, label: d.label })}
                      >
                        {d.label}
                      </Tag>
                    </Tooltip>
                  ))}
                </div>
              )}
              {step.status !== 'completed' && step.dataRefs.length > 0 && run?.memory_snapshot && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                  {step.dataRefs.map((d) => {
                    const snapshotKey = `has_${d.key}` as keyof typeof run.memory_snapshot;
                    const hasValue = !!(run.memory_snapshot as unknown as Record<string, boolean>)[snapshotKey];
                    if (!hasValue) return null;
                    return (
                      <Tooltip key={d.key} title="查看产出数据">
                        <Tag
                          icon={<EyeOutlined />}
                          color="green"
                          style={{ cursor: 'pointer', fontSize: 11 }}
                          onClick={() => setDataDrawer({ open: true, key: d.key, label: d.label })}
                        >
                          {d.label}
                        </Tag>
                      </Tooltip>
                    );
                  })}
                </div>
              )}
            </div>
          ),
          icon: getStepIcon(step.status),
        }))}
      />

      <Drawer
        title={
          <Space>
            <EditOutlined />
            <span>{editingPrompt?.label ?? '提示词编辑'}</span>
          </Space>
        }
        width={640}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        extra={
          <Space>
            <Button onClick={handleSave} loading={saving}>
              保存
            </Button>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleSaveAndRerun}
              loading={saving}
            >
              保存并从此步重跑
            </Button>
          </Space>
        }
      >
        {promptLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 100 }}>
            <LoadingOutlined style={{ fontSize: 24 }} />
          </div>
        ) : (
          <>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: 12 }}>
              {editingPrompt?.agent} / {editingPrompt?.name}.md
            </Text>
            <div style={{ height: 'calc(100vh - 200px)', border: '1px solid #d9d9d9', borderRadius: 6 }}>
              <Editor
                height="100%"
                defaultLanguage="markdown"
                value={promptContent}
                onChange={(val) => setPromptContent(val ?? '')}
                options={{
                  minimap: { enabled: false },
                  wordWrap: 'on',
                  fontSize: 13,
                  lineNumbers: 'on',
                }}
              />
            </div>
          </>
        )}
      </Drawer>

      {runId && (
        <DataPreviewDrawer
          open={dataDrawer.open}
          runId={runId}
          dataKey={dataDrawer.key}
          label={dataDrawer.label}
          onClose={() => setDataDrawer((s) => ({ ...s, open: false }))}
        />
      )}
    </div>
  );
}
