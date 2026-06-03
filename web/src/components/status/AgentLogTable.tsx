import { Table, Tag, Tooltip, Typography } from 'antd';
import type { AgentLog } from '../../types/run';

const { Text } = Typography;

const AGENT_LABELS: Record<string, string> = {
  research: '数据采集',
  product_analyst: '产品分析',
  keyword_strategist: '关键词策略',
  copywriter: '文案撰写',
  orchestrator: '调度器',
};

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  ok: { color: 'green', text: '成功' },
  error: { color: 'red', text: '失败' },
  waiting: { color: 'orange', text: '等待中' },
};

const columns = [
  {
    title: '时间',
    dataIndex: 'timestamp',
    key: 'timestamp',
    width: 100,
    render: (ts: string) => {
      try {
        return new Date(ts).toLocaleTimeString();
      } catch {
        return ts;
      }
    },
  },
  {
    title: 'Agent',
    dataIndex: 'agent',
    key: 'agent',
    width: 120,
    render: (agent: string) => (
      <Tag color="blue">{AGENT_LABELS[agent] ?? agent}</Tag>
    ),
  },
  {
    title: '操作',
    dataIndex: 'action',
    key: 'action',
    render: (action: string, record: AgentLog & Record<string, unknown>) => {
      if (action === 'error' && record.error) {
        return (
          <Tooltip title={String(record.traceback || record.error)} overlayStyle={{ maxWidth: 480 }}>
            <Text type="danger" ellipsis style={{ maxWidth: 300 }}>
              {String(record.error)}
            </Text>
          </Tooltip>
        );
      }
      return action;
    },
  },
  {
    title: '耗时',
    dataIndex: 'duration_ms',
    key: 'duration_ms',
    width: 80,
    render: (ms: number) => (ms > 0 ? `${(ms / 1000).toFixed(1)}s` : '--'),
  },
  {
    title: '状态',
    dataIndex: 'status',
    key: 'status',
    width: 80,
    render: (status: string) => {
      const info = STATUS_MAP[status] ?? STATUS_MAP.ok;
      return <Tag color={info.color}>{info.text}</Tag>;
    },
  },
];

interface Props {
  logs: AgentLog[];
}

export default function AgentLogTable({ logs }: Props) {
  return (
    <Table
      columns={columns}
      dataSource={logs.map((log, i) => ({ ...log, key: i }))}
      size="small"
      pagination={false}
      scroll={{ y: 300 }}
      locale={{ emptyText: '暂无执行日志' }}
    />
  );
}
