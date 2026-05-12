import { Card, Progress, Typography } from 'antd';
import CopyButton from './CopyButton';

const { Text } = Typography;

interface Props {
  title: string;
  content: string;
  currentCount: number;
  maxCount: number;
  unit: 'chars' | 'bytes';
  children?: React.ReactNode;
}

function getProgressStatus(current: number, max: number): 'success' | 'normal' | 'exception' {
  const ratio = current / max;
  if (ratio > 1) return 'exception';
  if (ratio > 0.9) return 'normal';
  return 'success';
}

export default function SectionCard({ title, content, currentCount, maxCount, unit, children }: Props) {
  const status = getProgressStatus(currentCount, maxCount);

  return (
    <Card
      size="small"
      title={
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Text strong>{title}</Text>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {currentCount} / {maxCount} {unit}
            </Text>
            <CopyButton text={content} />
          </div>
        </div>
      }
      style={{ marginBottom: 16 }}
    >
      <Progress
        percent={Math.min((currentCount / maxCount) * 100, 100)}
        size="small"
        status={status}
        showInfo={false}
        style={{ marginBottom: 12 }}
      />
      {children ?? (
        <div
          style={{
            background: '#fafafa',
            padding: 12,
            borderRadius: 6,
            whiteSpace: 'pre-wrap',
            fontFamily: 'monospace',
            fontSize: 13,
            maxHeight: 200,
            overflow: 'auto',
          }}
        >
          {content}
        </div>
      )}
    </Card>
  );
}
