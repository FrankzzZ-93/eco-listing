import { Table, Tag } from 'antd';
import type { AgentLog } from '../../types/run';

const columns = [
  {
    title: 'Time',
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
    width: 140,
    render: (agent: string) => (
      <Tag color="blue">{agent.replace('_', ' ')}</Tag>
    ),
  },
  {
    title: 'Action',
    dataIndex: 'action',
    key: 'action',
  },
  {
    title: 'Duration',
    dataIndex: 'duration_ms',
    key: 'duration_ms',
    width: 100,
    render: (ms: number) => (ms > 0 ? `${(ms / 1000).toFixed(1)}s` : '--'),
  },
  {
    title: 'Status',
    dataIndex: 'status',
    key: 'status',
    width: 80,
    render: (status: string) => {
      const color = status === 'ok' ? 'green' : status === 'error' ? 'red' : 'orange';
      return <Tag color={color}>{(status ?? 'ok').toUpperCase()}</Tag>;
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
    />
  );
}
