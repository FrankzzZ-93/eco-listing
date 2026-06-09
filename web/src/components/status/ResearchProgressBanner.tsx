import { Progress, Tag, Typography } from 'antd';
import type { ResearchProgress } from '../../types/run';

const { Text } = Typography;

const PHASE_LABELS: Record<string, string> = {
  competitor_listings: '竞品 Listing',
  alex: 'Alex 问答',
  reviews: '评论',
};

interface Props {
  progress: ResearchProgress;
}

export default function ResearchProgressBanner({ progress }: Props) {
  const { phase, done, total } = progress;
  const label = PHASE_LABELS[phase] ?? phase;
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;

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
      <Text strong>竞品采集中</Text>
      <Tag color="blue">{label}</Tag>
      <Text type="secondary">
        正在抓取{label}：第 {Math.min(done + 1, total)}/{total} 个
      </Text>
      <Progress
        percent={percent}
        size="small"
        style={{ flex: 1, marginBottom: 0, minWidth: 120 }}
      />
    </div>
  );
}
