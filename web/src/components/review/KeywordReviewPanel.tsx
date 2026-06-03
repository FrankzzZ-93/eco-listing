import { useState, useEffect, useMemo } from 'react';
import { Table, Button, Card, Alert, Input, Space, Tag, Popconfirm, message, Typography, Modal, Form, InputNumber, Select, Upload } from 'antd';
import { DeleteOutlined, SearchOutlined, SaveOutlined, PlusOutlined, EditOutlined, InboxOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { getRunData, submitKeywordReview, uploadFile } from '../../api/runs';
import type { PendingAction, MemorySnapshot } from '../../types/run';

const { Dragger } = Upload;

const { Text } = Typography;

interface KeywordItem {
  key: string;
  keyword: string;
  search_volume: number;
  competition: string;
  [k: string]: unknown;
}

interface Props {
  runId: string;
  pendingAction: PendingAction | null;
  memorySnapshot?: MemorySnapshot;
  onReviewComplete: () => void;
  onUploaded?: () => void;
}

export default function KeywordReviewPanel({ runId, pendingAction, memorySnapshot, onReviewComplete, onUploaded }: Props) {
  const isReviewing = pendingAction?.type === 'review_keywords';
  const hasData = memorySnapshot?.has_keyword_library;
  const needsApproval = hasData && !memorySnapshot?.has_classified_keywords;

  const [keywords, setKeywords] = useState<KeywordItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<KeywordItem | null>(null);
  const [uploading, setUploading] = useState(false);
  const [form] = Form.useForm();

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      await uploadFile(runId, file, 'keywords');
      message.success('关键词词库已上传，正在加载审核页…');
      // Backend auto-resumes to the keyword_review interrupt; refresh the run so
      // pending_action flips to review_keywords and this panel loads the data.
      onUploaded?.();
    } catch {
      message.error('上传失败，请确认文件为 .xlsx / .json 格式');
    } finally {
      setUploading(false);
    }
  };

  useEffect(() => {
    if (!isReviewing && !hasData) return;
    setLoading(true);
    getRunData(runId, 'keyword_library')
      .then((res) => {
        const raw = (res.data as Record<string, unknown>[]) || [];
        const items: KeywordItem[] = raw.map((item, i) => ({
          key: `kw_${i}`,
          keyword: String(item.keyword || ''),
          search_volume: Number(item.search_volume || 0),
          competition: String(item.competition || ''),
          ...item,
        }));
        setKeywords(items);
      })
      .catch(() => message.error('加载关键词词库失败'))
      .finally(() => setLoading(false));
  }, [isReviewing, hasData, runId]);

  const filteredKeywords = useMemo(() => {
    if (!searchText) return keywords;
    const lower = searchText.toLowerCase();
    return keywords.filter((k) => k.keyword.toLowerCase().includes(lower));
  }, [keywords, searchText]);

  const handleDelete = (key: string) => {
    setKeywords((prev) => prev.filter((k) => k.key !== key));
  };

  const handleBatchDelete = () => {
    setKeywords((prev) => prev.filter((k) => !selectedRowKeys.includes(k.key)));
    setSelectedRowKeys([]);
  };

  const handleAdd = () => {
    setEditingItem(null);
    form.resetFields();
    setModalOpen(true);
  };

  const handleEdit = (record: KeywordItem) => {
    setEditingItem(record);
    form.setFieldsValue({
      keyword: record.keyword,
      search_volume: record.search_volume,
      competition: record.competition,
    });
    setModalOpen(true);
  };

  const handleModalOk = () => {
    form.validateFields().then((values) => {
      if (editingItem) {
        setKeywords((prev) =>
          prev.map((k) =>
            k.key === editingItem.key
              ? { ...k, keyword: values.keyword, search_volume: values.search_volume, competition: values.competition }
              : k,
          ),
        );
      } else {
        const newItem: KeywordItem = {
          key: `kw_new_${Date.now()}`,
          keyword: values.keyword,
          search_volume: values.search_volume || 0,
          competition: values.competition || '低',
        };
        setKeywords((prev) => [newItem, ...prev]);
      }
      setModalOpen(false);
      form.resetFields();
    });
  };

  const handleApprove = async () => {
    setSubmitLoading(true);
    try {
      const cleaned = keywords.map(({ key: _key, ...rest }) => rest);
      await submitKeywordReview(runId, cleaned);
      message.success('关键词审核完成，流程继续');
      onReviewComplete();
    } catch {
      message.error('提交失败');
    } finally {
      setSubmitLoading(false);
    }
  };

  const columns: ColumnsType<KeywordItem> = [
    {
      title: '关键词',
      dataIndex: 'keyword',
      key: 'keyword',
      ellipsis: true,
      sorter: (a, b) => a.keyword.localeCompare(b.keyword),
    },
    {
      title: '搜索量',
      dataIndex: 'search_volume',
      key: 'search_volume',
      width: 120,
      sorter: (a, b) => a.search_volume - b.search_volume,
      defaultSortOrder: 'descend',
      render: (v: number) => v.toLocaleString(),
    },
    {
      title: '竞争度',
      dataIndex: 'competition',
      key: 'competition',
      width: 100,
      filters: [
        { text: '高', value: '高' },
        { text: '中', value: '中' },
        { text: '低', value: '低' },
      ],
      onFilter: (value, record) => record.competition === value,
      render: (v: string) => {
        const color = v === '高' ? 'red' : v === '中' ? 'orange' : 'green';
        return <Tag color={color}>{v || '-'}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Space size={0}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} />
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.key)} okText="删除" cancelText="取消">
            <Button type="link" danger size="small" icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (!isReviewing && !hasData) {
    return (
      <Card>
        <Alert
          message="暂无关键词词库"
          description="请上传关键词文件（.xlsx / .json），上传后将自动进入审核页面。"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Dragger
          accept=".xlsx,.json"
          multiple={false}
          showUploadList={false}
          disabled={uploading}
          beforeUpload={(file) => {
            handleUpload(file);
            return false;
          }}
          style={{ padding: '16px 0' }}
        >
          <p className="ant-upload-drag-icon" style={{ marginBottom: 8 }}>
            <InboxOutlined style={{ fontSize: 36, color: '#1677ff' }} />
          </p>
          <p className="ant-upload-text">{uploading ? '上传中…' : '点击或拖拽关键词文件到此处上传'}</p>
          <p className="ant-upload-hint" style={{ fontSize: 12 }}>
            支持鸥鹭 / 西柚导出的 .xlsx，或 .json 词库文件
          </p>
        </Dragger>
      </Card>
    );
  }

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Text strong style={{ fontSize: 16 }}>
          关键词词库审核
          <Tag style={{ marginLeft: 8 }}>{keywords.length} 条</Tag>
        </Text>
        <Space>
          <Input
            placeholder="搜索关键词"
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{ width: 200 }}
            allowClear
          />
          <Button type="primary" ghost icon={<PlusOutlined />} onClick={handleAdd}>
            新增
          </Button>
          {selectedRowKeys.length > 0 && (
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

      <Table
        columns={columns}
        dataSource={filteredKeywords}
        loading={loading}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys as string[]),
        }}
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: ['20', '50', '100', '200'] }}
        scroll={{ y: 480 }}
        rowKey="key"
      />

      {(isReviewing || needsApproval) && (
        <div style={{ marginTop: 16 }}>
          <Button type="primary" icon={<SaveOutlined />} loading={submitLoading} onClick={handleApprove}>
            确认词库，继续下一步
          </Button>
        </div>
      )}

      <Modal
        title={editingItem ? '编辑关键词' : '新增关键词'}
        open={modalOpen}
        onOk={handleModalOk}
        onCancel={() => setModalOpen(false)}
        okText={editingItem ? '保存' : '添加'}
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="keyword"
            label="关键词"
            rules={[{ required: true, message: '请输入关键词' }]}
          >
            <Input placeholder="输入关键词" />
          </Form.Item>
          <Form.Item
            name="search_volume"
            label="搜索量"
          >
            <InputNumber min={0} style={{ width: '100%' }} placeholder="输入搜索量" />
          </Form.Item>
          <Form.Item
            name="competition"
            label="竞争度"
          >
            <Select placeholder="选择竞争度">
              <Select.Option value="高">高</Select.Option>
              <Select.Option value="中">中</Select.Option>
              <Select.Option value="低">低</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
