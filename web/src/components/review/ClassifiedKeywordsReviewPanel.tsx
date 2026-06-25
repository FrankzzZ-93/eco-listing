import { useState, useEffect, useMemo, useRef } from 'react';
import { Table, Button, Card, Alert, Input, Space, Tag, Popconfirm, message, Typography, Select, Modal, Form, InputNumber } from 'antd';
import { DeleteOutlined, SearchOutlined, SaveOutlined, PlusOutlined, CheckCircleOutlined, DownloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { getRunData, submitClassifiedReview } from '../../api/runs';
import { downloadJson, downloadText, rowsToCsv } from '../../utils/download';
import type { PendingAction, MemorySnapshot, RunStatus } from '../../types/run';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

type Category = 'A' | 'B' | 'C' | 'D';

const CATEGORIES: Category[] = ['A', 'B', 'C', 'D'];

const CATEGORY_META: Record<Category, { label: string; color: string }> = {
  A: { label: 'A 大词/类目核心词', color: 'red' },
  B: { label: 'B 精准转化词', color: 'orange' },
  C: { label: 'C 场景长尾词', color: 'gold' },
  D: { label: 'D 写作排除词', color: 'default' },
};

interface ClassifiedRow {
  key: string;
  category: Category;
  keyword: string;
  translation: string;
  search_volume: number | null;
  bid_price: number | null;
  conversion_rate: number | null;
  rationale: string;
  usage: string;
  [k: string]: unknown;
}

interface Props {
  runId: string;
  pendingAction: PendingAction | null;
  memorySnapshot?: MemorySnapshot;
  runStatus?: RunStatus;
  onReviewComplete: () => void;
}

function num(val: unknown): number | null {
  if (val === null || val === undefined || val === '') return null;
  const n = Number(val);
  return Number.isFinite(n) ? n : null;
}

function flatten(raw: Record<string, unknown>): ClassifiedRow[] {
  const rows: ClassifiedRow[] = [];
  for (const cat of CATEGORIES) {
    const arr = Array.isArray(raw[cat]) ? (raw[cat] as Record<string, unknown>[]) : [];
    arr.forEach((item, i) => {
      rows.push({
        ...item,
        key: `${cat}_${i}`,
        category: cat,
        keyword: String(item.keyword ?? ''),
        translation: String(item.translation ?? ''),
        search_volume: num(item.search_volume),
        bid_price: num(item.bid_price),
        conversion_rate: num(item.conversion_rate),
        rationale: String(item.rationale ?? ''),
        usage: String(item.usage ?? ''),
      });
    });
  }
  return rows;
}

export default function ClassifiedKeywordsReviewPanel({ runId, pendingAction, memorySnapshot, runStatus, onReviewComplete }: Props) {
  const isReviewing = pendingAction?.type === 'review_classified_keywords';
  const hasData = memorySnapshot?.has_classified_keywords;
  // Editable while paused at the review gate (isReviewing) and also after the
  // run has settled, so the user can revise the classification and regenerate.
  // Read-only only while the graph is actively running.
  const isRunning = runStatus === 'running' || runStatus === 'pending';
  const editable = isReviewing || (!!hasData && !isRunning);

  const [rows, setRows] = useState<ClassifiedRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [approveLoading, setApproveLoading] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [form] = Form.useForm();

  // Preserve non-row metadata (semantic_map, summary, etc.) so it survives the
  // round-trip when the reviewed classification is submitted back.
  const originalRef = useRef<Record<string, unknown>>({});
  const [productDefinition, setProductDefinition] = useState('');

  useEffect(() => {
    if (!isReviewing && !hasData) return;
    setLoading(true);
    getRunData(runId, 'classified_keywords')
      .then((res) => {
        const raw = (res.data as Record<string, unknown>) || {};
        originalRef.current = raw;
        setRows(flatten(raw));
        const sm = raw.semantic_map as Record<string, unknown> | undefined;
        setProductDefinition(sm?.product_definition ? String(sm.product_definition) : '');
      })
      .catch(() => message.error('加载关键词分类失败'))
      .finally(() => setLoading(false));
  }, [isReviewing, hasData, runId]);

  const filteredRows = useMemo(() => {
    if (!searchText) return rows;
    const lower = searchText.toLowerCase();
    return rows.filter(
      (r) => r.keyword.toLowerCase().includes(lower) || r.translation.toLowerCase().includes(lower),
    );
  }, [rows, searchText]);

  const counts = useMemo(() => {
    const c: Record<Category, number> = { A: 0, B: 0, C: 0, D: 0 };
    for (const r of rows) c[r.category] += 1;
    return c;
  }, [rows]);

  const updateRow = (key: string, field: keyof ClassifiedRow, value: unknown) => {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, [field]: value } : r)));
  };

  const handleDelete = (key: string) => {
    setRows((prev) => prev.filter((r) => r.key !== key));
    setSelectedRowKeys((prev) => prev.filter((k) => k !== key));
  };

  const handleBatchDelete = () => {
    setRows((prev) => prev.filter((r) => !selectedRowKeys.includes(r.key)));
    setSelectedRowKeys([]);
  };

  const handleAdd = () => {
    form.resetFields();
    form.setFieldsValue({ category: 'B' });
    setAddModalOpen(true);
  };

  const handleAddOk = () => {
    form.validateFields().then((values) => {
      const newRow: ClassifiedRow = {
        key: `new_${Date.now()}`,
        category: (values.category as Category) ?? 'B',
        keyword: String(values.keyword ?? '').trim(),
        translation: String(values.translation ?? '').trim(),
        search_volume: num(values.search_volume),
        bid_price: num(values.bid_price),
        conversion_rate: num(values.conversion_rate),
        rationale: String(values.rationale ?? '').trim(),
        usage: String(values.usage ?? '').trim(),
      };
      setRows((prev) => [newRow, ...prev]);
      setAddModalOpen(false);
      form.resetFields();
    });
  };

  const buildPayload = (): Record<string, unknown> => {
    const grouped: Record<Category, Record<string, unknown>[]> = { A: [], B: [], C: [], D: [] };
    for (const row of rows) {
      const { key: _key, category, translation, search_volume, bid_price, conversion_rate, ...rest } = row;
      const entry: Record<string, unknown> = { ...rest };
      if (translation) entry.translation = translation;
      if (search_volume !== null) entry.search_volume = search_volume;
      if (bid_price !== null) entry.bid_price = bid_price;
      if (conversion_rate !== null) entry.conversion_rate = conversion_rate;
      grouped[category].push(entry);
    }
    const original = originalRef.current || {};
    const summary = (original.summary as Record<string, unknown>) || {};
    return {
      ...original,
      A: grouped.A,
      B: grouped.B,
      C: grouped.C,
      D: grouped.D,
      summary: {
        ...summary,
        total: rows.length,
        A_count: grouped.A.length,
        B_count: grouped.B.length,
        C_count: grouped.C.length,
        D_count: grouped.D.length,
      },
    };
  };

  const handleSave = async () => {
    setSaveLoading(true);
    try {
      await submitClassifiedReview(runId, buildPayload(), false);
      // Keep the new rows as canonical so they aren't recomputed away, and
      // refresh the metadata baseline used for the next round-trip.
      originalRef.current = buildPayload();
      message.success(
        isReviewing
          ? '已保存，可继续修改或点击「保存后通过」进入下一步'
          : '分类表已保存，可在「最终产出」点击「重新生成文案」应用最新分类',
      );
    } catch {
      message.error('保存失败');
    } finally {
      setSaveLoading(false);
    }
  };

  const exportName = `${runId}_classified_keywords`;
  const handleExportJson = () => downloadJson(`${exportName}.json`, buildPayload());
  const handleExportCsv = () => {
    const csv = rowsToCsv(
      rows as unknown as Record<string, unknown>[],
      [
        { key: 'keyword', label: '关键词' },
        { key: 'translation', label: '翻译' },
        { key: 'search_volume', label: '周搜索量' },
        { key: 'bid_price', label: 'CPC竞价($)' },
        { key: 'conversion_rate', label: '点击转化率(%)' },
        { key: 'category', label: '分类' },
        { key: 'rationale', label: '分类依据说明' },
        { key: 'usage', label: '推荐使用位置' },
      ],
    );
    downloadText(`${exportName}.csv`, csv, 'text/csv');
  };

  const handleApprove = async () => {
    setApproveLoading(true);
    try {
      await submitClassifiedReview(runId, buildPayload(), true);
      message.success('关键词分类已通过，流程继续生成文案');
      onReviewComplete();
    } catch {
      message.error('提交失败');
    } finally {
      setApproveLoading(false);
    }
  };

  const columns: ColumnsType<ClassifiedRow> = [
    {
      title: '关键词',
      dataIndex: 'keyword',
      key: 'keyword',
      width: 200,
      fixed: 'left',
      sorter: (a, b) => a.keyword.localeCompare(b.keyword),
      render: (_, record) => (
        <Input
          value={record.keyword}
          placeholder="关键词"
          disabled={!editable}
          onChange={(e) => updateRow(record.key, 'keyword', e.target.value)}
        />
      ),
    },
    {
      title: '翻译',
      dataIndex: 'translation',
      key: 'translation',
      width: 150,
      render: (v: string) => <Text type="secondary">{v || '-'}</Text>,
    },
    {
      title: '周搜索量',
      dataIndex: 'search_volume',
      key: 'search_volume',
      width: 100,
      sorter: (a, b) => (a.search_volume ?? 0) - (b.search_volume ?? 0),
      defaultSortOrder: 'descend',
      render: (v: number | null) => (v === null ? '-' : v.toLocaleString()),
    },
    {
      title: 'CPC竞价($)',
      dataIndex: 'bid_price',
      key: 'bid_price',
      width: 100,
      render: (v: number | null) => (v === null ? '-' : `$${v}`),
    },
    {
      title: '点击转化率(%)',
      dataIndex: 'conversion_rate',
      key: 'conversion_rate',
      width: 110,
      render: (v: number | null) => (v === null ? '-' : `${v}%`),
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 130,
      filters: CATEGORIES.map((c) => ({ text: CATEGORY_META[c].label, value: c })),
      onFilter: (value, record) => record.category === value,
      render: (v: Category, record) => (
        <Select
          value={v}
          style={{ width: '100%' }}
          disabled={!editable}
          onChange={(val) => updateRow(record.key, 'category', val)}
          options={CATEGORIES.map((c) => ({
            value: c,
            label: <Tag color={CATEGORY_META[c].color} style={{ marginRight: 0 }}>{c}</Tag>,
          }))}
        />
      ),
    },
    {
      title: '分类依据说明',
      dataIndex: 'rationale',
      key: 'rationale',
      width: 280,
      render: (_, record) => (
        <TextArea
          value={record.rationale}
          autoSize={{ minRows: 1, maxRows: 4 }}
          placeholder="分类依据"
          disabled={!editable}
          onChange={(e) => updateRow(record.key, 'rationale', e.target.value)}
        />
      ),
    },
    {
      title: '推荐使用位置',
      dataIndex: 'usage',
      key: 'usage',
      width: 220,
      render: (_, record) => (
        <TextArea
          value={record.usage}
          autoSize={{ minRows: 1, maxRows: 4 }}
          placeholder="推荐使用位置"
          disabled={!editable}
          onChange={(e) => updateRow(record.key, 'usage', e.target.value)}
        />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 60,
      fixed: 'right',
      render: (_, record) =>
        editable ? (
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.key)} okText="删除" cancelText="取消">
            <Button type="link" danger size="small" icon={<DeleteOutlined />} />
          </Popconfirm>
        ) : null,
    },
  ];

  if (!isReviewing && !hasData) {
    return (
      <Card>
        <Alert
          message="暂无关键词分类"
          description="流程尚未进行关键词分类，或正在运行中。请在「运行状态」标签页查看进度。"
          type="info"
          showIcon
        />
      </Card>
    );
  }

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <Text strong style={{ fontSize: 16 }}>
          {isReviewing ? '关键词分类审核' : '关键词分类'}
          <Tag style={{ marginLeft: 8 }}>{rows.length} 条</Tag>
          {CATEGORIES.map((c) => (
            <Tag key={c} color={CATEGORY_META[c].color} style={{ marginLeft: 4 }}>
              {c} {counts[c]}
            </Tag>
          ))}
        </Text>
        <Space>
          <Input
            placeholder="搜索关键词 / 翻译"
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{ width: 220 }}
            allowClear
          />
          <Button icon={<DownloadOutlined />} onClick={handleExportJson}>
            导出 JSON
          </Button>
          <Button icon={<DownloadOutlined />} onClick={handleExportCsv}>
            导出 CSV
          </Button>
          {editable && (
            <Button type="primary" ghost icon={<PlusOutlined />} onClick={handleAdd}>
              新增
            </Button>
          )}
          {editable && selectedRowKeys.length > 0 && (
            <Popconfirm
              title={`确认删除选中的 ${selectedRowKeys.length} 条？`}
              onConfirm={handleBatchDelete}
              okText="删除"
              cancelText="取消"
            >
              <Button danger icon={<DeleteOutlined />}>
                删除选中 ({selectedRowKeys.length})
              </Button>
            </Popconfirm>
          )}
        </Space>
      </div>

      {productDefinition && (
        <Alert
          message="产品语义定义"
          description={<Paragraph style={{ margin: 0 }}>{productDefinition}</Paragraph>}
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
        />
      )}

      <Table
        columns={columns}
        dataSource={filteredRows}
        loading={loading}
        rowSelection={
          editable
            ? {
                selectedRowKeys,
                onChange: (keys) => setSelectedRowKeys(keys as string[]),
              }
            : undefined
        }
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: ['20', '50', '100', '200'] }}
        scroll={{ x: 1200, y: 480 }}
        rowKey="key"
      />

      {isReviewing && (
        <div style={{ marginTop: 16 }}>
          <Space>
            <Button icon={<SaveOutlined />} loading={saveLoading} onClick={handleSave}>
              保存
            </Button>
            <Button type="primary" icon={<CheckCircleOutlined />} loading={approveLoading} onClick={handleApprove}>
              保存后通过
            </Button>
          </Space>
          <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
            「保存」仅暂存编辑，停留在审核；「保存后通过」后才会开始撰写 Listing。
          </Text>
        </div>
      )}

      {!isReviewing && editable && (
        <div style={{ marginTop: 16 }}>
          <Button type="primary" icon={<SaveOutlined />} loading={saveLoading} onClick={handleSave}>
            保存修改
          </Button>
          <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
            修改后保存，再到「最终产出」点击「重新生成文案」即可用最新分类重写 Listing。
          </Text>
        </div>
      )}

      <Modal
        title="新增关键词分类"
        open={addModalOpen}
        onOk={handleAddOk}
        onCancel={() => setAddModalOpen(false)}
        okText="添加"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="keyword" label="关键词" rules={[{ required: true, message: '请输入关键词' }]}>
            <Input placeholder="输入关键词" />
          </Form.Item>
          <Form.Item name="category" label="分类" rules={[{ required: true, message: '请选择分类' }]}>
            <Select
              placeholder="选择分类"
              options={CATEGORIES.map((c) => ({ value: c, label: CATEGORY_META[c].label }))}
            />
          </Form.Item>
          <Form.Item name="translation" label="翻译">
            <Input placeholder="输入中文翻译（可选）" />
          </Form.Item>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item name="search_volume" label="周搜索量">
              <InputNumber min={0} style={{ width: '100%' }} placeholder="搜索量" />
            </Form.Item>
            <Form.Item name="bid_price" label="CPC竞价($)">
              <InputNumber min={0} step={0.01} style={{ width: '100%' }} placeholder="竞价" />
            </Form.Item>
            <Form.Item name="conversion_rate" label="点击转化率(%)">
              <InputNumber min={0} step={0.01} style={{ width: '100%' }} placeholder="转化率" />
            </Form.Item>
          </Space>
          <Form.Item name="rationale" label="分类依据说明">
            <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} placeholder="为什么归入该分类（可选）" />
          </Form.Item>
          <Form.Item name="usage" label="推荐使用位置">
            <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} placeholder="如标题 / 五点 / ST（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
