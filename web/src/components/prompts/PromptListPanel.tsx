import { Table, Tag } from 'antd';
import type { PromptMeta } from '../../types/prompt';

const AGENT_LABELS: Record<string, string> = {
  research: '数据采集',
  product_analyst: '产品分析',
  keyword_strategist: '关键词策略',
  copywriter: '文案撰写',
  orchestrator: '调度器',
};

interface Props {
  prompts: PromptMeta[];
  selectedKey: string | null;
  onSelect: (prompt: PromptMeta) => void;
}

export default function PromptListPanel({ prompts, selectedKey, onSelect }: Props) {
  const columns = [
    {
      title: 'Agent',
      dataIndex: 'agent',
      key: 'agent',
      width: 120,
      render: (agent: string) => AGENT_LABELS[agent] ?? agent,
    },
    {
      title: '提示词',
      dataIndex: 'filename',
      key: 'filename',
    },
    {
      title: '状态',
      dataIndex: 'modified',
      key: 'modified',
      width: 90,
      render: (modified: boolean) =>
        modified ? (
          <Tag color="orange">已修改</Tag>
        ) : (
          <Tag color="default">默认</Tag>
        ),
    },
  ];

  return (
    <Table
      columns={columns}
      dataSource={prompts.map((p) => ({ ...p, key: `${p.agent}/${p.name}` }))}
      size="small"
      pagination={false}
      locale={{ emptyText: '暂无提示词' }}
      rowClassName={(record) =>
        `${record.agent}/${record.name}` === selectedKey ? 'ant-table-row-selected' : ''
      }
      onRow={(record) => ({
        onClick: () => onSelect(record as PromptMeta),
        style: { cursor: 'pointer' },
      })}
    />
  );
}
