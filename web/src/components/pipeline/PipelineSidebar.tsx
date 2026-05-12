import { Steps, Typography } from 'antd';
import {
  LoadingOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import type { RunDetail } from '../../types/run';

const { Text } = Typography;

type StepStatus = 'running' | 'completed' | 'waiting' | 'pending' | 'error';

interface PipelineStep {
  key: string;
  title: string;
  status: StepStatus;
  description?: string;
}

function getStepIcon(status: StepStatus) {
  switch (status) {
    case 'running':
      return <LoadingOutlined style={{ color: '#1677ff' }} />;
    case 'completed':
      return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    case 'waiting':
      return <ExclamationCircleOutlined style={{ color: '#faad14' }} />;
    case 'error':
      return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    default:
      return <ClockCircleOutlined style={{ color: '#d9d9d9' }} />;
  }
}

function computeSteps(run: RunDetail | undefined): PipelineStep[] {
  if (!run) {
    return defaultSteps();
  }

  const { memory_snapshot: mem, status, current_agent, pending_action } = run;

  const steps: PipelineStep[] = [
    {
      key: 'research',
      title: 'Research',
      status: mem.has_competitor_listings
        ? 'completed'
        : current_agent === 'research'
        ? 'running'
        : 'pending',
      description: mem.has_competitor_listings ? 'Data collected' : undefined,
    },
    {
      key: 'product_analyst',
      title: 'Product Analyst',
      status: mem.has_product_attributes_draft
        ? 'completed'
        : current_agent === 'product_analyst'
        ? 'running'
        : 'pending',
    },
    {
      key: 'review',
      title: 'Human Review',
      status: pending_action?.type === 'review_product_attributes'
        ? 'waiting'
        : mem.has_approved_product_attributes
        ? 'completed'
        : 'pending',
      description:
        pending_action?.type === 'review_product_attributes'
          ? 'Action required'
          : undefined,
    },
    {
      key: 'keyword_strategist',
      title: 'Keyword Classification',
      status: mem.has_classified_keywords
        ? 'completed'
        : current_agent === 'keyword_strategist' && !mem.has_final_listing
        ? 'running'
        : 'pending',
    },
    {
      key: 'copywriter',
      title: 'Copywriter',
      status: mem.has_final_listing
        ? 'completed'
        : current_agent === 'copywriter'
        ? 'running'
        : 'pending',
      description: current_agent === 'copywriter' ? 'R1/R2/R3' : undefined,
    },
    {
      key: 'st_optimization',
      title: 'ST Optimization',
      status: mem.has_final_st
        ? 'completed'
        : current_agent === 'keyword_strategist' && mem.has_final_listing
        ? 'running'
        : 'pending',
    },
  ];

  if (status === 'failed') {
    const firstPending = steps.findIndex((s) => s.status === 'running');
    if (firstPending >= 0) {
      steps[firstPending].status = 'error';
    }
  }

  return steps;
}

function defaultSteps(): PipelineStep[] {
  return [
    { key: 'research', title: 'Research', status: 'pending' },
    { key: 'product_analyst', title: 'Product Analyst', status: 'pending' },
    { key: 'review', title: 'Human Review', status: 'pending' },
    { key: 'keyword_strategist', title: 'Keyword Classification', status: 'pending' },
    { key: 'copywriter', title: 'Copywriter', status: 'pending' },
    { key: 'st_optimization', title: 'ST Optimization', status: 'pending' },
  ];
}

interface Props {
  run: RunDetail | undefined;
}

export default function PipelineSidebar({ run }: Props) {
  const steps = computeSteps(run);

  return (
    <div style={{ padding: '16px 12px' }}>
      <Text strong style={{ display: 'block', marginBottom: 16 }}>
        Pipeline Progress
      </Text>
      <Steps
        direction="vertical"
        size="small"
        items={steps.map((step) => ({
          title: step.title,
          description: step.description,
          icon: getStepIcon(step.status),
        }))}
      />
    </div>
  );
}
