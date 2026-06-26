import { useState, useEffect, useMemo } from 'react';
import { Table, Card, Alert, Input, Space, Tag, message, Typography, Upload, Button } from 'antd';
import { SearchOutlined, InboxOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { getRunData, uploadFile, rerunFromKeywords } from '../../api/runs';
import type { PendingAction, MemorySnapshot, RunStatus } from '../../types/run';

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
  runStatus?: RunStatus;
  onReviewComplete: () => void;
  onUploaded?: () => void;
}

// The keyword library is always user-provided, so there is no review gate: once
// uploaded the run auto-proceeds to classification. This panel therefore
// (a) collects the upload when the library is missing, (b) shows a read-only
// view of the uploaded library, and (c) once the run has settled, lets the user
// re-upload a fresh library to re-classify + re-write the listing (reuse a
// finished record when traffic words change).
export default function KeywordReviewPanel({ runId, memorySnapshot, runStatus, onReviewComplete, onUploaded }: Props) {
  const hasData = memorySnapshot?.has_keyword_library;
  const isRunning = runStatus === 'running' || runStatus === 'pending';

  const [keywords, setKeywords] = useState<KeywordItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [uploading, setUploading] = useState(false);
  const [rerunning, setRerunning] = useState(false);

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      await uploadFile(runId, file, 'keywords');
      message.success('关键词词库已上传，正在自动进入关键词分类…');
      onUploaded?.();
    } catch {
      message.error('上传失败，请确认文件为 .xlsx / .json 格式');
    } finally {
      setUploading(false);
    }
  };

  const handleReupload = async (file: File) => {
    setRerunning(true);
    try {
      await rerunFromKeywords(runId, file);
      message.success('已上传新词库，正在重新分类并重写 Listing…');
      onReviewComplete();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail ? `重新执行失败：${detail}` : '重新执行失败，请确认文件为 .xlsx / .json');
    } finally {
      setRerunning(false);
    }
  };

  useEffect(() => {
    if (!hasData) return;
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
  }, [hasData, runId]);

  const filteredKeywords = useMemo(() => {
    if (!searchText) return keywords;
    const lower = searchText.toLowerCase();
    return keywords.filter((k) => k.keyword.toLowerCase().includes(lower));
  }, [keywords, searchText]);

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
  ];

  if (!hasData) {
    return (
      <Card>
        <Alert
          message="暂无关键词词库"
          description="请上传关键词文件（.xlsx / .json）。上传后将跳过审核，自动进入关键词分类环节。"
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
          关键词词库
          <Tag style={{ marginLeft: 8 }}>{keywords.length} 条</Tag>
        </Text>
        <Input
          placeholder="搜索关键词"
          prefix={<SearchOutlined />}
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          style={{ width: 200 }}
          allowClear
        />
      </div>

      <Alert
        message="关键词词库已上传，无需审核，流程会自动进入关键词分类。此处仅供查看。"
        type="success"
        showIcon
        style={{ marginBottom: 16 }}
      />

      {!isRunning && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="更新流量词，重跑后续流程"
          description={
            <div>
              <div style={{ marginBottom: 8 }}>
                竞争态势变化后，下载最新流量词上传到这里，即可用新词库
                <b>重新分类 → 重写 Listing</b>（保留本条记录，不必从头跑；会在分类审核处暂停供复核）。
              </div>
              <Dragger
                accept=".xlsx,.json"
                multiple={false}
                showUploadList={false}
                disabled={rerunning}
                beforeUpload={(file) => {
                  handleReupload(file);
                  return false;
                }}
                style={{ padding: '8px 0' }}
              >
                <p style={{ margin: 0 }}>
                  <Button type="primary" icon={<ReloadOutlined />} loading={rerunning}>
                    {rerunning ? '上传中…' : '上传新词库并重新执行'}
                  </Button>
                </p>
                <p className="ant-upload-hint" style={{ fontSize: 12, marginTop: 8 }}>
                  点击或拖拽 .xlsx / .json 词库文件
                </p>
              </Dragger>
            </div>
          }
        />
      )}

      <Table
        columns={columns}
        dataSource={filteredKeywords}
        loading={loading}
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: ['20', '50', '100', '200'] }}
        scroll={{ y: 480 }}
        rowKey="key"
      />
    </Card>
  );
}
