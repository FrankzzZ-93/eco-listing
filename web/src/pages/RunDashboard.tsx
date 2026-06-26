import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout, Tabs, Card, Spin, Typography, Alert, Button, Space, Modal, message, notification, Result, Descriptions, Tag } from 'antd';
import { ArrowLeftOutlined, PauseCircleOutlined, StopOutlined, PlayCircleOutlined, CheckCircleFilled, FileTextOutlined, DeleteOutlined } from '@ant-design/icons';
import PipelineSidebar from '../components/pipeline/PipelineSidebar';
import AgentLogTable from '../components/status/AgentLogTable';
import DataPreviewCollapse from '../components/status/DataPreviewCollapse';
import LiveCodexBanner from '../components/status/LiveCodexBanner';
import ResearchProgressBanner from '../components/status/ResearchProgressBanner';
import AttributesReviewPanel from '../components/review/AttributesReviewPanel';
import KeywordReviewPanel from '../components/review/KeywordReviewPanel';
import ClassifiedKeywordsReviewPanel from '../components/review/ClassifiedKeywordsReviewPanel';
import ListingPreview from '../components/output/ListingPreview';
import CaptchaModal from '../components/common/CaptchaModal';
import { useRunStatus } from '../hooks/useRunStatus';
import { getFinal, pauseRun, resumeRun, stopRun, submitCaptcha, deleteRun, regenerateListing, updateProductName } from '../api/runs';
import type { FinalOutput } from '../types/listing';

const { Sider, Content } = Layout;
const { Title, Text } = Typography;

export default function RunDashboard() {
  const { runId, tab } = useParams<{ runId: string; tab?: string }>();
  const navigate = useNavigate();
  const { run, isLoading, refresh } = useRunStatus(runId);

  const [activeTab, setActiveTab] = useState(tab || 'status');
  const [finalOutput, setFinalOutput] = useState<FinalOutput | null>(null);
  const [finalLoading, setFinalLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [captchaLoading, setCaptchaLoading] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const loadFinal = useCallback(() => {
    if (!runId) return;
    setFinalLoading(true);
    getFinal(runId)
      .then(setFinalOutput)
      .catch(() => {})
      .finally(() => setFinalLoading(false));
  }, [runId]);

  const isCaptchaGate =
    run?.status === 'waiting_human' && run.pending_action?.type === 'solve_captcha';

  const handleCaptchaSubmit = async (answer: string) => {
    setCaptchaLoading(true);
    try {
      await submitCaptcha(runId!, answer);
      message.success('已提交验证，正在继续抓取…');
      refresh();
    } catch (e) {
      reportActionError('提交验证', e);
    } finally {
      setCaptchaLoading(false);
    }
  };

  const handleReviewComplete = () => {
    setActiveTab('status');
    refresh();
  };

  useEffect(() => {
    if (tab) setActiveTab(tab);
  }, [tab]);

  useEffect(() => {
    if (run?.status === 'waiting_human') {
      const pt = run.pending_action?.type;
      if (pt === 'upload_keywords') {
        setActiveTab('keyword-review');
      } else if (pt === 'review_classified_keywords') {
        setActiveTab('classified-review');
      } else if (pt === 'review_product_attributes') {
        setActiveTab('attr-review');
      }
    }
  }, [run?.status, run?.pending_action?.type]);

  const prevStatusRef = useRef(run?.status);
  useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = run?.status;
    if (run?.status === 'failed' && prev !== 'failed') {
      notification.error({
        message: '任务执行出错',
        description: run.error || '流程执行过程中遇到错误，请查看运行状态了解详情。',
        duration: 0,
        placement: 'topRight',
      });
      setActiveTab('status');
    }
    if (run?.status === 'completed' && prev !== 'completed') {
      setActiveTab('output');
      // Reload so a *regenerated* listing replaces the previous output (the
      // has_final_* flags stay true across a regen, so the effect below won't
      // re-fire on its own).
      loadFinal();
    }
  }, [run?.status, run?.error, loadFinal]);

  useEffect(() => {
    if (run?.memory_snapshot?.has_final_listing && run?.memory_snapshot?.has_final_st) {
      loadFinal();
    }
  }, [run?.memory_snapshot?.has_final_listing, run?.memory_snapshot?.has_final_st, loadFinal]);

  const handleTabChange = (key: string) => {
    setActiveTab(key);
    navigate(`/run/${runId}/${key}`, { replace: true });
  };

  const reportActionError = (action: string, e: unknown) => {
    const err = e as { response?: { status?: number; data?: { detail?: string } } };
    const status = err?.response?.status;
    const detail = err?.response?.data?.detail;
    if (status === 404) {
      message.error(`${action}失败：该任务在后端已不存在（页面可能已过期），正在刷新…`);
      refresh();
      return;
    }
    if (detail) {
      message.error(`${action}失败：${detail}`);
      refresh();
      return;
    }
    message.error(`${action}失败：无法连接后端服务，请确认服务已启动`);
  };

  const handlePause = async () => {
    setActionLoading(true);
    try {
      await pauseRun(runId!);
      message.success('任务已暂停');
    } catch (e) {
      reportActionError('暂停', e);
    } finally {
      setActionLoading(false);
    }
  };

  const handleResume = async () => {
    setActionLoading(true);
    try {
      await resumeRun(runId!);
      message.success('任务已恢复');
    } catch (e) {
      reportActionError('恢复', e);
    } finally {
      setActionLoading(false);
    }
  };

  const handleStop = () => {
    Modal.confirm({
      title: '确认停止任务？',
      content: '停止后任务将无法恢复，已产出的中间数据会保留。',
      okText: '确认停止',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        setActionLoading(true);
        try {
          await stopRun(runId!);
          message.success('任务已停止');
          refresh();
        } catch (e) {
          reportActionError('停止', e);
        } finally {
          setActionLoading(false);
        }
      },
    });
  };

  const handleRenameProduct = async (name: string) => {
    try {
      await updateProductName(runId!, name.trim());
      message.success('产品名称已更新');
      refresh();
    } catch {
      message.error('产品名称更新失败');
    }
  };

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      await regenerateListing(runId!);
      message.success('已开始重新生成文案，使用最新属性表与关键词分类…');
      setActiveTab('status');
      refresh();
    } catch (e) {
      reportActionError('重新生成', e);
    } finally {
      setRegenerating(false);
    }
  };

  const handleDelete = () => {
    Modal.confirm({
      title: '确认删除任务？',
      content: '将停止并永久删除该任务，已产出的中间数据会一并清除，且无法恢复。',
      okText: '停止并删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        setActionLoading(true);
        try {
          await deleteRun(runId!);
          message.success('任务已删除');
          navigate('/new');
        } catch (e) {
          reportActionError('删除', e);
        } finally {
          setActionLoading(false);
        }
      },
    });
  };

  if (isLoading && !run) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', paddingTop: 100, flexDirection: 'column', gap: 16 }}>
        <Spin size="large" />
        <Typography.Text type="secondary">正在加载任务状态…</Typography.Text>
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space align="center">
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/new')}
          >
            返回
          </Button>
          <Text
            strong
            style={{ fontSize: 16 }}
            // Only editable when the run is settled: a rename during execution
            // could be clobbered by the running node's next checkpoint write.
            editable={
              run && run.status !== 'running' && run.status !== 'pending'
                ? {
                    text: run.product_name || '',
                    tooltip: '点击修改产品名称（方便复用记录）',
                    onChange: handleRenameProduct,
                  }
                : false
            }
          >
            {run?.product_name || '未命名'}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{runId}</Text>
        </Space>
        <Space>
          {run?.status === 'running' && (
            <Button
              icon={<PauseCircleOutlined />}
              onClick={handlePause}
              loading={actionLoading}
            >
              暂停
            </Button>
          )}
          {(run?.status === 'paused' || run?.status === 'failed') && (
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleResume}
              loading={actionLoading}
            >
              {run?.status === 'failed' ? '重试' : '继续'}
            </Button>
          )}
          {(run?.status === 'running' || run?.status === 'paused' || run?.status === 'waiting_human') && (
            <Button
              danger
              icon={<StopOutlined />}
              onClick={handleStop}
              loading={actionLoading}
            >
              停止
            </Button>
          )}
          <Button
            danger
            icon={<DeleteOutlined />}
            onClick={handleDelete}
            loading={actionLoading}
          >
            删除
          </Button>
        </Space>
      </div>
      <Layout style={{ background: 'transparent', minHeight: 'calc(100vh - 130px)' }}>
        <Sider
          width={280}
          style={{
            background: '#fff',
            borderRadius: 8,
            marginRight: 16,
            overflow: 'auto',
          }}
        >
          <PipelineSidebar run={run} runId={runId} />
        </Sider>

        <Content>
          {run?.status === 'completed' && finalOutput?.final_listing && (
            <Card style={{ marginBottom: 16 }}>
              <Result
                status="success"
                title="任务已完成"
                subTitle={runId}
                extra={
                  <Button type="primary" icon={<FileTextOutlined />} onClick={() => setActiveTab('output')}>
                    查看最终产出
                  </Button>
                }
              />
              <Descriptions size="small" bordered column={2} style={{ marginTop: -16 }}>
                <Descriptions.Item label="标题">
                  {(() => {
                    const t = finalOutput.final_listing.title ?? '';
                    return t.length > 80 ? t.slice(0, 80) + '…' : t;
                  })()}
                </Descriptions.Item>
                <Descriptions.Item label="五点描述">
                  {(finalOutput.final_listing.bullet_points ?? []).length} 条
                </Descriptions.Item>
                <Descriptions.Item label="Search Terms">
                  {(() => {
                    const bytes = finalOutput.word_frequency_report?.total_bytes;
                    const count = (finalOutput.final_st ?? []).length;
                    return (
                      <Space>
                        <Tag>{count} 个词</Tag>
                        {bytes !== undefined && (
                          <Tag color={bytes > 249 ? 'red' : 'green'}>{bytes} 字节</Tag>
                        )}
                      </Space>
                    );
                  })()}
                </Descriptions.Item>
                <Descriptions.Item label="关键词使用">
                  {(() => {
                    const r = finalOutput.word_frequency_report;
                    if (!r) return <Tag>暂无</Tag>;
                    return (
                      <Space>
                        <Tag color="blue">文案 {r.used_in_listing}</Tag>
                        <Tag color="purple">ST {r.added_to_st}</Tag>
                        <Text type="secondary" style={{ fontSize: 12 }}>共 {r.total_keywords}</Text>
                      </Space>
                    );
                  })()}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          )}
          <Card style={{ minHeight: 500 }}>
            <Tabs
              activeKey={activeTab}
              onChange={handleTabChange}
              items={[
                {
                  key: 'status',
                  label: '运行状态',
                  children: (
                    <div>
                      {run?.status === 'running' && (
                        <Alert
                          message="任务正在执行中"
                          description="系统正在自动处理，请耐心等待。页面会每 3 秒自动刷新状态。"
                          type="info"
                          showIcon
                          style={{ marginBottom: 16 }}
                        />
                      )}
                      {run?.status === 'paused' && (
                        <Alert
                          message="任务已暂停"
                          description="点击上方「继续」按钮可恢复执行。"
                          type="warning"
                          showIcon
                          style={{ marginBottom: 16 }}
                        />
                      )}
                      {run?.status === 'stopped' && (
                        <Alert
                          message="任务已停止"
                          description="任务已被手动停止，已产出的中间数据可查看。"
                          type="error"
                          showIcon
                          style={{ marginBottom: 16 }}
                        />
                      )}
                      {run?.status === 'failed' && (
                        <Alert
                          message="任务执行出错"
                          description={
                            <div>
                              <div>{run.error || '执行过程中发生未知错误'}</div>
                              <Button
                                type="primary"
                                size="small"
                                style={{ marginTop: 8 }}
                                icon={<PlayCircleOutlined />}
                                onClick={handleResume}
                                loading={actionLoading}
                              >
                                重试
                              </Button>
                            </div>
                          }
                          type="error"
                          showIcon
                          style={{ marginBottom: 16 }}
                        />
                      )}
                      {run?.status === 'waiting_human' &&
                        run.pending_action?.type === 'upload_competitor_data' && (
                          <Alert
                            message="未能自动获取竞品 Listing"
                            description={
                              <div>
                                <div>
                                  系统未能抓取到竞品 Listing 数据。你可以重新尝试抓取（会保留已上传的评论/词库，只补抓缺失的 Listing 与
                                  Alex），或在「属性审核」前手动上传竞品 Listing。
                                </div>
                                <Button
                                  type="primary"
                                  size="small"
                                  style={{ marginTop: 8 }}
                                  icon={<PlayCircleOutlined />}
                                  onClick={handleResume}
                                  loading={actionLoading}
                                >
                                  重新抓取竞品数据
                                </Button>
                              </div>
                            }
                            type="warning"
                            showIcon
                            style={{ marginBottom: 16 }}
                          />
                        )}
                      <Title level={5}>执行日志</Title>
                      {run?.status === 'running' && run.research_progress && (
                        <ResearchProgressBanner progress={run.research_progress} />
                      )}
                      {run?.status === 'running' && run.live_codex && (
                        <LiveCodexBanner progress={run.live_codex} />
                      )}
                      <AgentLogTable logs={run?.agent_log ?? []} />
                      <div style={{ marginTop: 24 }}>
                        <DataPreviewCollapse memorySnapshot={run?.memory_snapshot} runId={runId!} />
                      </div>
                    </div>
                  ),
                },
                {
                  key: 'attr-review',
                  label: '属性审核',
                  children: (
                    <AttributesReviewPanel
                      runId={runId!}
                      pendingAction={run?.pending_action ?? null}
                      memorySnapshot={run?.memory_snapshot}
                      runStatus={run?.status}
                      onReviewComplete={handleReviewComplete}
                    />
                  ),
                },
                {
                  key: 'keyword-review',
                  label: '关键词词库',
                  children: (
                    <KeywordReviewPanel
                      runId={runId!}
                      pendingAction={run?.pending_action ?? null}
                      memorySnapshot={run?.memory_snapshot}
                      runStatus={run?.status}
                      onReviewComplete={handleReviewComplete}
                      onUploaded={refresh}
                    />
                  ),
                },
                {
                  key: 'classified-review',
                  label: '分类审核',
                  children: (
                    <ClassifiedKeywordsReviewPanel
                      runId={runId!}
                      pendingAction={run?.pending_action ?? null}
                      memorySnapshot={run?.memory_snapshot}
                      runStatus={run?.status}
                      onReviewComplete={handleReviewComplete}
                    />
                  ),
                },
                {
                  key: 'output',
                  label: '最终产出',
                  children: (
                    <ListingPreview
                      output={finalOutput}
                      loading={finalLoading}
                      runId={runId}
                      canRegenerate={
                        !!run?.memory_snapshot?.has_classified_keywords &&
                        run?.status !== 'running' &&
                        run?.status !== 'pending'
                      }
                      regenerating={regenerating}
                      onRegenerate={handleRegenerate}
                    />
                  ),
                },
              ]}
            />
          </Card>
        </Content>
      </Layout>

      <CaptchaModal
        open={!!isCaptchaGate}
        message={run?.pending_action?.message}
        imageUrl={run?.pending_action?.image_url}
        loading={captchaLoading}
        onSubmit={handleCaptchaSubmit}
      />
    </div>
  );
}
