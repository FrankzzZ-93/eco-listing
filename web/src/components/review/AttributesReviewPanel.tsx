import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Button,
  Space,
  Alert,
  Input,
  Typography,
  Divider,
  Collapse,
  Spin,
  Row,
  Col,
  message,
} from 'antd';
import { EditOutlined, CodeOutlined } from '@ant-design/icons';
import EditableStringList from './EditableStringList';
import EditablePairList from './EditablePairList';
import FullMarkdownEditor from './FullMarkdownEditor';
import { submitReview, getRunData } from '../../api/runs';
import type { PendingAction, MemorySnapshot } from '../../types/run';

const { Text, Title } = Typography;
const { TextArea } = Input;

interface Props {
  runId: string;
  pendingAction: PendingAction | null;
  memorySnapshot?: MemorySnapshot;
  onReviewComplete: () => void;
}

function ensureArray(val: unknown): string[] {
  if (Array.isArray(val)) return val.map(String);
  return [];
}

function ensureObjArray(val: unknown): Record<string, string>[] {
  if (Array.isArray(val)) return val.map((v) => (typeof v === 'object' && v ? v : {}) as Record<string, string>);
  return [];
}

function ensureStr(val: unknown): string {
  if (typeof val === 'string') return val;
  if (val == null) return '';
  return String(val);
}

function ensureObj(val: unknown): Record<string, unknown> {
  return (typeof val === 'object' && val && !Array.isArray(val)) ? val as Record<string, unknown> : {};
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Row gutter={8} style={{ marginBottom: 12 }} align="top">
      <Col flex="140px">
        <Text strong style={{ fontSize: 13, lineHeight: '32px' }}>{label}</Text>
      </Col>
      <Col flex="auto">{children}</Col>
    </Row>
  );
}

function SubFieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Row gutter={8} style={{ marginBottom: 8 }} align="top">
      <Col flex="120px">
        <Text type="secondary" style={{ fontSize: 12, lineHeight: '32px' }}>{label}</Text>
      </Col>
      <Col flex="auto">{children}</Col>
    </Row>
  );
}

type AttrData = Record<string, unknown>;

// Strip ASIN source-labels the analyst sometimes emits when competitor values
// differ (e.g. "B0XXXXXXXX: value; 其他ASIN无数据"), so the panel shows content
// only. Mirrors the backend sanitizer in product_analyst.py.
const ASIN_RE = /\bB0[A-Z0-9]{8}\b/gi;
const ASIN_LABEL_RE = /(?:B0[A-Z0-9]{8})(?:\s*\/\s*B0[A-Z0-9]{8})*\s*[:：]\s*/gi;
const ASIN_FILLER_RE = /[；;，,]?\s*其他\s*ASIN[^；;]*/gi;

function stripAsinText(text: string): string {
  let s = text.replace(ASIN_LABEL_RE, '');
  s = s.replace(ASIN_FILLER_RE, '');
  s = s.replace(ASIN_RE, '');
  s = s.replace(/\s*[；;]\s*[；;]+/g, '； ');
  s = s.replace(/^[\s；;，,:：/]+/, '');
  s = s.replace(/[\s；;，,]+$/, '');
  s = s.replace(/[ \t]{2,}/g, ' ');
  return s.trim();
}

function stripAsins(obj: unknown): unknown {
  if (typeof obj === 'string') return stripAsinText(obj);
  if (Array.isArray(obj)) return obj.map(stripAsins);
  if (obj && typeof obj === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) out[k] = stripAsins(v);
    return out;
  }
  return obj;
}

function buildInitialData(raw: unknown): AttrData {
  if (!raw || typeof raw !== 'object') return {};
  return stripAsins(JSON.parse(JSON.stringify(raw))) as AttrData;
}

export default function AttributesReviewPanel({
  runId,
  pendingAction,
  memorySnapshot,
  onReviewComplete,
}: Props) {
  const isPending = pendingAction?.type === 'review_product_attributes';
  const hasData = memorySnapshot?.has_product_attributes_draft;

  const [data, setData] = useState<AttrData>({});
  const [loading, setLoading] = useState(false);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [rejectMode, setRejectMode] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [jsonEditorOpen, setJsonEditorOpen] = useState(false);

  useEffect(() => {
    if (isPending && pendingAction?.data && Object.keys(pendingAction.data).length > 0) {
      setData(buildInitialData(pendingAction.data));
      return;
    }
    if (isPending || hasData) {
      setLoading(true);
      getRunData(runId, 'product_attributes_draft')
        .then((res) => setData(buildInitialData(res.data)))
        .catch(() => message.error('加载属性表失败'))
        .finally(() => setLoading(false));
    }
  }, [isPending, hasData, runId, pendingAction?.data]);

  const updateField = useCallback((path: string[], value: unknown) => {
    setData((prev) => {
      const next = JSON.parse(JSON.stringify(prev));
      let obj = next;
      for (let i = 0; i < path.length - 1; i++) {
        if (!obj[path[i]] || typeof obj[path[i]] !== 'object') obj[path[i]] = {};
        obj = obj[path[i]];
      }
      obj[path[path.length - 1]] = value;
      return next;
    });
  }, []);

  const getVal = useCallback((path: string[]): unknown => {
    let obj: unknown = data;
    for (const key of path) {
      if (!obj || typeof obj !== 'object') return undefined;
      obj = (obj as Record<string, unknown>)[key];
    }
    return obj;
  }, [data]);

  if (!isPending && !hasData) {
    return (
      <Card>
        <Alert
          message="暂无待审核内容"
          description="流程正在运行或尚未生成产品属性表。请在「运行状态」标签页查看进度。"
          type="info"
          showIcon
        />
      </Card>
    );
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}>
        <Spin size="large" />
      </div>
    );
  }

  const handleApprove = async () => {
    setSubmitLoading(true);
    try {
      await submitReview(runId, { type: 'product_attributes', approved_data: data });
      message.success('审核已提交');
      onReviewComplete();
    } catch {
      message.error('提交失败');
    } finally {
      setSubmitLoading(false);
    }
  };

  const handleReject = async () => {
    setSubmitLoading(true);
    try {
      await submitReview(runId, { type: 'product_attributes', approved_data: {}, feedback });
      message.success('已驳回，Agent 将重新生成');
      onReviewComplete();
    } catch {
      message.error('驳回失败');
    } finally {
      setSubmitLoading(false);
    }
  };

  const handleJsonSave = (content: string) => {
    try {
      const parsed = JSON.parse(content);
      setData(parsed);
      setJsonEditorOpen(false);
      message.success('JSON 已应用');
    } catch {
      message.error('JSON 格式错误');
    }
  };

  const basicInfo = ensureObj(data.basic_info);
  const productName = ensureObj(basicInfo.product_name);
  const productDim = ensureObj(basicInfo.product_dimensions);
  const packageDim = ensureObj(basicInfo.package_dimensions);
  const colorSpec = ensureObj(basicInfo.color_spec_quantity);
  const applicable = ensureObj(basicInfo.applicable);
  const marketAnalysis = ensureObj(data.market_analysis);
  const copywritingRef = ensureObj(data.copywriting_ref);

  const collapseItems = [
    {
      key: 'basic_info',
      label: <Title level={5} style={{ margin: 0 }}>基础产品信息</Title>,
      children: (
        <div>
          <FieldRow label="产品名称">
            <SubFieldRow label="核心品类词">
              <Input
                value={ensureStr(productName.core_category_word)}
                onChange={(e) => updateField(['basic_info', 'product_name', 'core_category_word'], e.target.value)}
              />
            </SubFieldRow>
            <SubFieldRow label="关键识别词">
              <Input
                value={ensureStr(productName.key_identifiers)}
                onChange={(e) => updateField(['basic_info', 'product_name', 'key_identifiers'], e.target.value)}
              />
            </SubFieldRow>
          </FieldRow>

          <FieldRow label="产品尺寸">
            <SubFieldRow label="尺寸">
              <Input value={ensureStr(productDim.size)} onChange={(e) => updateField(['basic_info', 'product_dimensions', 'size'], e.target.value)} />
            </SubFieldRow>
            <SubFieldRow label="重量">
              <Input value={ensureStr(productDim.weight)} onChange={(e) => updateField(['basic_info', 'product_dimensions', 'weight'], e.target.value)} />
            </SubFieldRow>
          </FieldRow>

          <FieldRow label="包装尺寸">
            <SubFieldRow label="尺寸">
              <Input value={ensureStr(packageDim.size)} onChange={(e) => updateField(['basic_info', 'package_dimensions', 'size'], e.target.value)} />
            </SubFieldRow>
            <SubFieldRow label="重量">
              <Input value={ensureStr(packageDim.weight)} onChange={(e) => updateField(['basic_info', 'package_dimensions', 'weight'], e.target.value)} />
            </SubFieldRow>
          </FieldRow>

          <FieldRow label="材质">
            <Input
              value={ensureStr(basicInfo.material)}
              onChange={(e) => updateField(['basic_info', 'material'], e.target.value)}
            />
          </FieldRow>

          <FieldRow label="颜色/规格/数量">
            <SubFieldRow label="颜色">
              <Input value={ensureStr(colorSpec.colors)} onChange={(e) => updateField(['basic_info', 'color_spec_quantity', 'colors'], e.target.value)} />
            </SubFieldRow>
            <SubFieldRow label="规格">
              <Input value={ensureStr(colorSpec.specs)} onChange={(e) => updateField(['basic_info', 'color_spec_quantity', 'specs'], e.target.value)} />
            </SubFieldRow>
            <SubFieldRow label="包装数量">
              <Input value={ensureStr(colorSpec.package_quantity)} onChange={(e) => updateField(['basic_info', 'color_spec_quantity', 'package_quantity'], e.target.value)} />
            </SubFieldRow>
          </FieldRow>

          <FieldRow label="适用范围">
            <SubFieldRow label="目标用户">
              <TextArea autoSize={{ minRows: 1, maxRows: 3 }} value={ensureStr(applicable.target_users)} onChange={(e) => updateField(['basic_info', 'applicable', 'target_users'], e.target.value)} />
            </SubFieldRow>
            <SubFieldRow label="使用场景">
              <TextArea autoSize={{ minRows: 1, maxRows: 3 }} value={ensureStr(applicable.use_cases)} onChange={(e) => updateField(['basic_info', 'applicable', 'use_cases'], e.target.value)} />
            </SubFieldRow>
            <SubFieldRow label="兼容设备">
              <TextArea autoSize={{ minRows: 1, maxRows: 3 }} value={ensureStr(applicable.compatible_devices)} onChange={(e) => updateField(['basic_info', 'applicable', 'compatible_devices'], e.target.value)} />
            </SubFieldRow>
            <SubFieldRow label="不适用场景">
              <TextArea autoSize={{ minRows: 1, maxRows: 3 }} value={ensureStr(applicable.not_applicable)} onChange={(e) => updateField(['basic_info', 'applicable', 'not_applicable'], e.target.value)} />
            </SubFieldRow>
          </FieldRow>

          <FieldRow label="功能特性">
            <EditableStringList
              value={ensureArray(basicInfo.features)}
              onChange={(v) => updateField(['basic_info', 'features'], v)}
              placeholder="输入功能描述"
            />
          </FieldRow>

          <FieldRow label="包装内容">
            <EditableStringList
              value={ensureArray(basicInfo.package_contents)}
              onChange={(v) => updateField(['basic_info', 'package_contents'], v)}
              placeholder="输入物品及数量"
            />
          </FieldRow>

          <FieldRow label="认证">
            <Input
              value={ensureStr(basicInfo.certifications)}
              onChange={(e) => updateField(['basic_info', 'certifications'], e.target.value)}
            />
          </FieldRow>

          <FieldRow label="保修">
            <Input
              value={ensureStr(basicInfo.warranty)}
              onChange={(e) => updateField(['basic_info', 'warranty'], e.target.value)}
            />
          </FieldRow>

          <FieldRow label="Rufus 买家关注点">
            <EditablePairList
              value={ensureObjArray(basicInfo.rufus_concerns)}
              onChange={(v) => updateField(['basic_info', 'rufus_concerns'], v)}
              field1={{ key: 'question', label: '问题', placeholder: '买家关注问题' }}
              field2={{ key: 'answer', label: '回答', placeholder: '综合回答' }}
            />
          </FieldRow>
        </div>
      ),
    },
    {
      key: 'market_analysis',
      label: <Title level={5} style={{ margin: 0 }}>竞品市场分析</Title>,
      children: (
        <div>
          <FieldRow label="市场标配">
            <EditableStringList
              value={ensureArray(marketAnalysis.market_standard)}
              onChange={(v) => updateField(['market_analysis', 'market_standard'], v)}
              placeholder="输入市场标配项"
            />
          </FieldRow>

          <FieldRow label="差异化优势">
            <TextArea
              autoSize={{ minRows: 2, maxRows: 6 }}
              value={ensureStr(marketAnalysis.differentiation)}
              onChange={(e) => updateField(['market_analysis', 'differentiation'], e.target.value)}
              placeholder="待人工复核补充"
            />
          </FieldRow>

          <FieldRow label="已知痛点">
            <EditablePairList
              value={ensureObjArray(marketAnalysis.known_pain_points)}
              onChange={(v) => updateField(['market_analysis', 'known_pain_points'], v)}
              field1={{ key: 'pain_point', label: '痛点描述', placeholder: '痛点' }}
              field2={{ key: 'source', label: '来源', placeholder: 'listing / 评论' }}
            />
          </FieldRow>

          <FieldRow label="禁用信息">
            <EditablePairList
              value={ensureObjArray(marketAnalysis.prohibited_info)}
              onChange={(v) => updateField(['market_analysis', 'prohibited_info'], v)}
              field1={{ key: 'content', label: '禁止内容', placeholder: '内容' }}
              field2={{ key: 'reason', label: '原因', placeholder: '原因' }}
            />
          </FieldRow>
        </div>
      ),
    },
    {
      key: 'copywriting_ref',
      label: <Title level={5} style={{ margin: 0 }}>文案优化参考</Title>,
      children: (
        <div>
          <FieldRow label="核心亮点">
            <EditablePairList
              value={ensureObjArray(copywritingRef.core_highlights)}
              onChange={(v) => updateField(['copywriting_ref', 'core_highlights'], v)}
              field1={{ key: 'highlight', label: '亮点', placeholder: '亮点内容' }}
              field2={{ key: 'reason', label: '打动买家原因', placeholder: '原因' }}
            />
          </FieldRow>

          <FieldRow label="术语转化">
            <EditablePairList
              value={ensureObjArray(copywritingRef.tech_term_conversion)}
              onChange={(v) => updateField(['copywriting_ref', 'tech_term_conversion'], v)}
              field1={{ key: 'original', label: '技术词', placeholder: '原文' }}
              field2={{ key: 'converted', label: '大白话', placeholder: '转化后' }}
            />
          </FieldRow>
        </div>
      ),
    },
  ];

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Text strong style={{ fontSize: 16 }}>
          {isPending ? '产品属性表审核' : '产品属性表'}
        </Text>
        <Button icon={<CodeOutlined />} size="small" onClick={() => setJsonEditorOpen(true)}>
          JSON 编辑
        </Button>
      </div>

      {isPending && pendingAction?.agent_notes && (
        <Alert
          message="Agent 备注"
          description={pendingAction.agent_notes}
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Collapse
        defaultActiveKey={['basic_info', 'market_analysis', 'copywriting_ref']}
        items={collapseItems}
        style={{ background: 'transparent' }}
      />

      <Divider style={{ margin: '16px 0' }} />

      {isPending ? (
        rejectMode ? (
          <div>
            <TextArea
              placeholder="请输入驳回原因（选填）…"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              rows={3}
              style={{ marginBottom: 12 }}
            />
            <Space>
              <Button danger loading={submitLoading} onClick={handleReject}>确认驳回</Button>
              <Button onClick={() => setRejectMode(false)}>取消</Button>
            </Space>
          </div>
        ) : (
          <Space>
            <Button type="primary" loading={submitLoading} onClick={handleApprove}>通过</Button>
            <Button loading={submitLoading} onClick={handleApprove}>修改后通过</Button>
            <Button danger onClick={() => setRejectMode(true)}>驳回</Button>
          </Space>
        )
      ) : (
        <Button type="primary" icon={<EditOutlined />} loading={submitLoading} onClick={handleApprove}>
          保存修改
        </Button>
      )}

      <FullMarkdownEditor
        open={jsonEditorOpen}
        content={JSON.stringify(data, null, 2)}
        onSave={handleJsonSave}
        onClose={() => setJsonEditorOpen(false)}
      />
    </Card>
  );
}
