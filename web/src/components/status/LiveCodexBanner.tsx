import { LoadingOutlined } from '@ant-design/icons';
import { Spin, Tag, Typography } from 'antd';
import type { LiveCodexProgress } from '../../types/run';

const { Text } = Typography;

const EVENT_TYPE_LABELS: Record<string, string> = {
  web_search: 'web 搜索',
  command_execution: '执行命令',
  mcp_tool_call: 'MCP 调用',
  reasoning: '推理中',
  agent_message: '生成回复',
  message: '生成回复',
  unknown: '未知阶段',
};

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  return `${m}m ${s}s`;
}

interface Props {
  progress: LiveCodexProgress;
}

export default function LiveCodexBanner({ progress }: Props) {
  const eventType = progress.current_event_type;
  const phaseLabel = eventType
    ? EVENT_TYPE_LABELS[eventType] ?? eventType
    : '启动中';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 12px',
        marginBottom: 12,
        border: '1px solid var(--ant-color-border, #e8e8e8)',
        borderRadius: 6,
        background: 'var(--ant-color-fill-quaternary, rgba(0,0,0,0.02))',
      }}
    >
      <Spin indicator={<LoadingOutlined spin />} size="small" />
      <Text strong>codex 进行中</Text>
      <Tag color="blue">{phaseLabel}</Tag>
      <Text type="secondary">已用 {formatElapsed(progress.elapsed_s)}</Text>
      <Text type="secondary">完成 {progress.items_completed} 项</Text>
    </div>
  );
}
