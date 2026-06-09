import { useState } from 'react';
import { Typography, Empty, Tag, Button } from 'antd';
import { CheckCircleFilled, ClockCircleOutlined, EyeOutlined } from '@ant-design/icons';
import type { MemorySnapshot } from '../../types/run';
import DataPreviewDrawer from './DataPreviewDrawer';

const { Text } = Typography;

interface DataItem {
  key: string;
  label: string;
  snapshotKey: keyof MemorySnapshot;
}

const ALL_ITEMS: DataItem[] = [
  { key: 'competitor_listings', label: '竞品 Listing 数据', snapshotKey: 'has_competitor_listings' },
  { key: 'customer_reviews', label: '竞品评论数据', snapshotKey: 'has_customer_reviews' },
  { key: 'review_summary', label: '评论摘要', snapshotKey: 'has_review_summary' },
  { key: 'alex_questions', label: 'Alex 问答', snapshotKey: 'has_alex_questions' },
  { key: 'product_attributes_draft', label: '产品属性表（初稿）', snapshotKey: 'has_product_attributes_draft' },
  { key: 'approved_product_attributes', label: '产品属性表（已审核）', snapshotKey: 'has_approved_product_attributes' },
  { key: 'keyword_library', label: '关键词词库', snapshotKey: 'has_keyword_library' },
  { key: 'classified_keywords', label: '分类关键词', snapshotKey: 'has_classified_keywords' },
  { key: 'final_listing', label: '最终 Listing', snapshotKey: 'has_final_listing' },
  { key: 'final_st', label: '最终 Search Terms', snapshotKey: 'has_final_st' },
];

interface Props {
  memorySnapshot: MemorySnapshot | undefined;
  runId: string;
}

export default function DataPreviewCollapse({ memorySnapshot, runId }: Props) {
  const [drawerState, setDrawerState] = useState<{ open: boolean; key: string; label: string }>({
    open: false, key: '', label: '',
  });

  if (!memorySnapshot) {
    return <Empty description="暂无数据" />;
  }

  const hasAny = ALL_ITEMS.some((item) => memorySnapshot[item.snapshotKey]);

  if (!hasAny) {
    return <Empty description="流程执行中，数据尚未产出" />;
  }

  return (
    <div>
      <Text strong style={{ display: 'block', marginBottom: 12 }}>
        已产出数据
      </Text>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {ALL_ITEMS.map((item) => {
          const available = memorySnapshot[item.snapshotKey];
          return (
            <div
              key={item.key}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 12px',
                background: available ? '#f6ffed' : '#fafafa',
                borderRadius: 6,
                border: `1px solid ${available ? '#b7eb8f' : '#f0f0f0'}`,
              }}
            >
              {available ? (
                <CheckCircleFilled style={{ color: '#52c41a' }} />
              ) : (
                <ClockCircleOutlined style={{ color: '#d9d9d9' }} />
              )}
              <Text style={{ color: available ? '#262626' : '#bfbfbf', flex: 1 }}>
                {item.label}
              </Text>
              {available && (
                <Button
                  type="link"
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={() => setDrawerState({ open: true, key: item.key, label: item.label })}
                  style={{ padding: '0 4px' }}
                >
                  查看
                </Button>
              )}
            </div>
          );
        })}
      </div>

      <DataPreviewDrawer
        open={drawerState.open}
        runId={runId}
        dataKey={drawerState.key}
        label={drawerState.label}
        onClose={() => setDrawerState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}
