import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card, Button, Space, Input, InputNumber, Select, Switch, Image, Empty, Spin,
  Typography, message, Row, Col, Tooltip, Collapse, Upload, Tag, Divider, Alert, theme,
} from 'antd';
import type { UploadProps } from 'antd';
import {
  ArrowLeftOutlined, PictureOutlined, DownloadOutlined, ThunderboltOutlined,
  CheckCircleFilled, UploadOutlined, PlusOutlined,
} from '@ant-design/icons';
import {
  startGeneration, listJobs, listCompetitorImages, uploadReferenceImage, imagesZipUrl,
  urlBasename, type ImageJob, type RefImage, type CompetitorImageGroup,
} from '../api/images';
import { getFinal } from '../api/runs';
import type { FinalOutput } from '../types/listing';
import { downloadUrlAsFile } from '../utils/download';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

const SIZE_OPTIONS = [
  { label: '1024×1024 方形', value: '1024x1024' },
  { label: '1536×1024 横向', value: '1536x1024' },
  { label: '1024×1536 纵向', value: '1024x1536' },
  { label: '2048×2048 2K 方形', value: '2048x2048' },
];

const QUALITY_OPTIONS = [
  { label: '高', value: 'high' },
  { label: '中', value: 'medium' },
  { label: '低（快）', value: 'low' },
];

const POLL_INTERVAL_MS = 4000;

function stripHtml(html: string): string {
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  return (tmp.textContent || tmp.innerText || '').trim();
}

interface FormDraft {
  prompt: string;
  size: string;
  count: number;
  quality: string;
  whiteBg: boolean;
  refs: string[];
}

function loadDraft(runId: string): Partial<FormDraft> {
  try {
    return JSON.parse(localStorage.getItem(`imgstudio:${runId}`) || '{}');
  } catch {
    return {};
  }
}

export default function ImageStudio() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { token } = theme.useToken();
  const draft = runId ? loadDraft(runId) : {};

  const [prompt, setPrompt] = useState(draft.prompt ?? '');
  const [size, setSize] = useState(draft.size ?? '1024x1024');
  const [count, setCount] = useState(draft.count ?? 1);
  const [quality, setQuality] = useState(draft.quality ?? 'high');
  const [whiteBg, setWhiteBg] = useState(draft.whiteBg ?? true);
  const [submitting, setSubmitting] = useState(false);

  const [jobs, setJobs] = useState<ImageJob[] | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorImageGroup[]>([]);
  const [uploaded, setUploaded] = useState<RefImage[]>([]);
  const [listing, setListing] = useState<FinalOutput | null>(null);

  // Selected reference image URLs (competitor / uploaded / previously generated).
  const [refs, setRefs] = useState<Set<string>>(new Set(draft.refs ?? []));

  // Persist the form draft so a refresh keeps the prompt / settings / selection.
  useEffect(() => {
    if (!runId) return;
    const d: FormDraft = { prompt, size, count, quality, whiteBg, refs: Array.from(refs) };
    localStorage.setItem(`imgstudio:${runId}`, JSON.stringify(d));
  }, [runId, prompt, size, count, quality, whiteBg, refs]);

  const refreshJobs = useCallback(async () => {
    if (!runId) return;
    try {
      setJobs(await listJobs(runId));
    } catch {
      setJobs([]);
    }
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    refreshJobs();
    listCompetitorImages(runId).then(setCompetitors).catch(() => setCompetitors([]));
    getFinal(runId).then(setListing).catch(() => setListing(null));
  }, [runId, refreshJobs]);

  // Poll while any job is running; stop automatically when none remain.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    const anyRunning = (jobs ?? []).some((j) => j.status === 'running');
    if (!anyRunning) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }
    if (pollRef.current) return; // already polling
    pollRef.current = setInterval(refreshJobs, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [jobs, refreshJobs]);

  const toggleRef = (url: string) => {
    setRefs((prev) => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  };

  const appendPrompt = (text: string) => {
    setPrompt((p) => (p.trim() ? `${p.trim()}\n${text}` : text));
  };

  const fillFromListing = () => {
    if (!listing?.final_listing) return;
    const l = listing.final_listing;
    const bullets = (l.bullet_points ?? []).map((b) => `- ${b}`).join('\n');
    setPrompt([
      `产品：${l.title ?? ''}`,
      bullets ? `核心卖点：\n${bullets}` : '',
      '请据此生成一张高质量的亚马逊商品图，突出产品外观与主要卖点。',
    ].filter(Boolean).join('\n\n'));
  };

  const handleUpload: UploadProps['customRequest'] = async (opt) => {
    if (!runId) return;
    try {
      const img = await uploadReferenceImage(runId, opt.file as File);
      setUploaded((u) => [img, ...u]);
      setRefs((prev) => new Set(prev).add(img.url));
      opt.onSuccess?.(img);
      message.success('参考图已上传');
    } catch (e) {
      opt.onError?.(e as Error);
      message.error('参考图上传失败');
    }
  };

  const handleGenerate = async () => {
    if (!runId) return;
    if (!prompt.trim()) { message.warning('请输入生图描述'); return; }
    setSubmitting(true);
    try {
      const job = await startGeneration(runId, {
        prompt: prompt.trim(), n: count, size, quality, whiteBg, referenceUrls: Array.from(refs),
      });
      setJobs((prev) => [job, ...(prev ?? [])]); // optimistic; polling reconciles
      message.success('已开始生成，可在下方任务中查看进度');
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(`提交失败：${err?.response?.data?.detail ?? '请重试'}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDownloadOne = async (url: string) => {
    try {
      await downloadUrlAsFile(url, urlBasename(url));
    } catch {
      message.error('下载失败，请重试');
    }
  };

  const renderSelectable = (img: RefImage, box = 96) => {
    const selected = refs.has(img.url);
    return (
      <Tooltip key={img.url} title={selected ? '已选为参考，点击取消' : '点击选为参考图'}>
        <div
          onClick={() => toggleRef(img.url)}
          style={{ position: 'relative', cursor: 'pointer', borderRadius: 8, padding: 2, border: `2px solid ${selected ? token.colorPrimary : 'transparent'}` }}
        >
          <img src={img.url} width={box} height={box} style={{ objectFit: 'cover', borderRadius: 6, display: 'block', border: `1px solid ${token.colorBorderSecondary}` }} />
          {selected && <CheckCircleFilled style={{ position: 'absolute', top: 6, right: 6, color: token.colorPrimary, fontSize: 18, background: token.colorBgContainer, borderRadius: '50%' }} />}
        </div>
      </Tooltip>
    );
  };

  const hasCompetitors = competitors.some((g) => g.images.length > 0);
  const hasJobs = !!jobs && jobs.length > 0;
  const l = listing?.final_listing;

  return (
    <div>
      <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(`/run/${runId}/output`)}>返回产出</Button>
        <Title level={4} style={{ margin: 0 }}><PictureOutlined /> 商品图生成</Title>
        <Text type="secondary" style={{ fontSize: 12 }}>{runId}</Text>
        {refs.size > 0 && <Tag color="blue">已选 {refs.size} 张参考图</Tag>}
      </div>

      <Row gutter={16}>
        <Col xs={24} lg={9}>
          <Card title="生成设置" size="small">
            <Space direction="vertical" style={{ width: '100%' }} size={14}>
              {l && (
                <Collapse
                  size="small"
                  items={[{
                    key: 'listing',
                    label: '本品 Listing 文案（可填入）',
                    children: (
                      <Space direction="vertical" style={{ width: '100%' }} size={8}>
                        <Button size="small" type="primary" ghost block icon={<PlusOutlined />} onClick={fillFromListing}>
                          一键生成基础提示词
                        </Button>
                        <Divider style={{ margin: '4px 0' }} />
                        <PrefillRow label="标题" text={l.title ?? ''} onInsert={appendPrompt} />
                        {(l.bullet_points ?? []).map((bp, i) => (
                          <PrefillRow key={i} label={`卖点${i + 1}`} text={bp} onInsert={appendPrompt} />
                        ))}
                        {l.description && <PrefillRow label="描述" text={stripHtml(l.description)} onInsert={appendPrompt} />}
                      </Space>
                    ),
                  }]}
                />
              )}

              <div>
                <Text strong>提示词</Text>
                <TextArea rows={6} value={prompt} onChange={(e) => setPrompt(e.target.value)}
                  placeholder="描述要生成的商品图，例如：白色陶瓷马克杯，木质桌面，柔和影棚光，浅景深" style={{ marginTop: 6 }} />
              </div>

              <Row gutter={12}>
                <Col span={12}>
                  <Text strong>尺寸</Text>
                  <Select value={size} onChange={setSize} options={SIZE_OPTIONS} style={{ width: '100%', marginTop: 6 }} />
                </Col>
                <Col span={6}>
                  <Text strong>质量</Text>
                  <Select value={quality} onChange={setQuality} options={QUALITY_OPTIONS} style={{ width: '100%', marginTop: 6 }} />
                </Col>
                <Col span={6}>
                  <Text strong>数量</Text>
                  <InputNumber min={1} max={6} value={count} onChange={(v) => setCount(v ?? 1)} style={{ width: '100%', marginTop: 6 }} />
                </Col>
              </Row>

              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Switch checked={whiteBg} onChange={setWhiteBg} />
                <Tooltip title="生成纯白底，适合作亚马逊主图"><Text>纯白背景（主图）</Text></Tooltip>
              </div>

              <Button type="primary" icon={<ThunderboltOutlined />} loading={submitting} onClick={handleGenerate} block>
                开始生成{refs.size ? `（带 ${refs.size} 张参考）` : ''}
              </Button>
              <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
                后台生成（约 1-3 分钟），可刷新/离开页面，结果会保存在下方任务中。无需 API Key。
              </Paragraph>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={15}>
          <Card
            title="参考图（点击选用，保持产品一致）" size="small" style={{ marginBottom: 16 }}
            extra={
              <Upload customRequest={handleUpload} showUploadList={false} accept="image/png,image/jpeg,image/webp">
                <Button size="small" icon={<UploadOutlined />}>上传参考图</Button>
              </Upload>
            }
          >
            <Space direction="vertical" style={{ width: '100%' }} size={10}>
              {uploaded.length > 0 && (
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>已上传</Text>
                  <div style={{ marginTop: 6 }}><Space wrap size={[8, 8]}>{uploaded.map((img) => renderSelectable(img))}</Space></div>
                </div>
              )}
              {hasCompetitors ? (
                competitors.map((g) => g.images.length > 0 && (
                  <div key={g.asin}>
                    <Text type="secondary" style={{ fontSize: 12 }}>竞品 {g.asin}</Text>
                    <div style={{ marginTop: 6 }}><Space wrap size={[8, 8]}>{g.images.map((img) => renderSelectable(img))}</Space></div>
                  </div>
                ))
              ) : uploaded.length === 0 ? (
                <Empty description="暂无竞品图（抓取竞品时自动保存）；可上传本地参考图" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : null}
            </Space>
          </Card>

          <Card
            title={`生成任务${hasJobs ? `（${jobs!.length}）` : ''}`} size="small"
            extra={hasJobs && (
              <Button size="small" icon={<DownloadOutlined />} href={imagesZipUrl(runId!)} target="_blank">批量下载 ZIP</Button>
            )}
          >
            {jobs === null ? (
              <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
            ) : !hasJobs ? (
              <Empty description="还没有生成任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                {jobs.map((job) => renderJob(job))}
              </Space>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );

  function renderJob(job: ImageJob) {
    const time = new Date(job.created_at * 1000).toLocaleString();
    return (
      <Card key={job.id} size="small" type="inner"
        title={
          <Space size={6} wrap>
            <JobStatusTag status={job.status} />
            <Text style={{ fontSize: 13, maxWidth: 360 }} ellipsis={{ tooltip: job.prompt }}>{job.prompt}</Text>
          </Space>
        }
        extra={<Text type="secondary" style={{ fontSize: 11 }}>{time}</Text>}
      >
        <Space size={4} wrap style={{ marginBottom: job.images.length || job.status !== 'completed' ? 8 : 0 }}>
          <Tag>{job.size}</Tag>
          <Tag>质量 {job.quality}</Tag>
          <Tag>{job.n} 张</Tag>
          {job.white_bg && <Tag color="default">白底</Tag>}
          {job.reference_urls?.length > 0 && <Tag color="blue">{job.reference_urls.length} 参考</Tag>}
        </Space>

        {job.status === 'running' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Spin size="small" /> <Text type="secondary">生成中（约 1-3 分钟）…</Text>
          </div>
        )}
        {job.status === 'failed' && <Alert type="error" showIcon message="生成失败" description={job.error || '未知错误'} />}
        {job.status === 'completed' && job.images.length > 0 && (
          <Image.PreviewGroup>
            <Space wrap size={[10, 10]}>
              {job.images.map((url) => {
                const selected = refs.has(url);
                return (
                  <div key={url} style={{ textAlign: 'center' }}>
                    <Image src={url} width={150} height={150}
                      style={{ objectFit: 'cover', borderRadius: 6, border: `2px solid ${selected ? token.colorPrimary : token.colorBorderSecondary}` }} />
                    <div style={{ marginTop: 2 }}>
                      <Button type="link" size="small" onClick={() => toggleRef(url)}>{selected ? '取消参考' : '设为参考'}</Button>
                      <Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => handleDownloadOne(url)}>下载</Button>
                    </div>
                  </div>
                );
              })}
            </Space>
          </Image.PreviewGroup>
        )}
      </Card>
    );
  }
}

function JobStatusTag({ status }: { status: ImageJob['status'] }) {
  if (status === 'running') return <Tag color="processing">生成中</Tag>;
  if (status === 'completed') return <Tag color="success">已完成</Tag>;
  return <Tag color="error">失败</Tag>;
}

function PrefillRow({ label, text, onInsert }: { label: string; text: string; onInsert: (t: string) => void }) {
  if (!text) return null;
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
      <Tag style={{ flexShrink: 0 }}>{label}</Tag>
      <Text style={{ flex: 1, fontSize: 12 }} ellipsis={{ tooltip: text }}>{text}</Text>
      <Button size="small" type="link" style={{ padding: 0, flexShrink: 0 }} onClick={() => onInsert(text)}>插入</Button>
    </div>
  );
}
