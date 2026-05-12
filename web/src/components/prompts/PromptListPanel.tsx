import { Table, Tag } from 'antd';
import type { PromptMeta } from '../../types/prompt';

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
      width: 140,
      render: (agent: string) => agent.replace('_', ' '),
    },
    {
      title: 'Prompt',
      dataIndex: 'filename',
      key: 'filename',
    },
    {
      title: 'Status',
      dataIndex: 'modified',
      key: 'modified',
      width: 100,
      render: (modified: boolean) =>
        modified ? (
          <Tag color="orange">Modified *</Tag>
        ) : (
          <Tag color="default">Default</Tag>
        ),
    },
  ];

  return (
    <Table
      columns={columns}
      dataSource={prompts.map((p) => ({ ...p, key: `${p.agent}/${p.name}` }))}
      size="small"
      pagination={false}
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
