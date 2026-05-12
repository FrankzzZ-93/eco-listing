import { Collapse, Typography, Empty } from 'antd';
import type { MemorySnapshot } from '../../types/run';

const { Text } = Typography;

interface Props {
  memorySnapshot: MemorySnapshot | undefined;
}

export default function DataPreviewCollapse({ memorySnapshot }: Props) {
  if (!memorySnapshot) {
    return <Empty description="No data collected yet" />;
  }

  const items = [
    {
      key: 'competitor_listings',
      label: 'Competitor Listings',
      available: memorySnapshot.has_competitor_listings,
    },
    {
      key: 'review_summary',
      label: 'Review Summary',
      available: memorySnapshot.has_review_summary,
    },
    {
      key: 'rufus_questions',
      label: 'Rufus Questions',
      available: memorySnapshot.has_rufus_questions,
    },
    {
      key: 'classified_keywords',
      label: 'Classified Keywords',
      available: memorySnapshot.has_classified_keywords,
    },
    {
      key: 'final_listing',
      label: 'Final Listing',
      available: memorySnapshot.has_final_listing,
    },
    {
      key: 'final_st',
      label: 'Final Search Terms',
      available: memorySnapshot.has_final_st,
    },
  ].filter((item) => item.available);

  if (items.length === 0) {
    return <Empty description="Pipeline running, no data available yet" />;
  }

  return (
    <div>
      <Text strong style={{ display: 'block', marginBottom: 12 }}>
        Collected Data
      </Text>
      <Collapse
        size="small"
        items={items.map((item) => ({
          key: item.key,
          label: item.label,
          children: (
            <Text type="secondary">
              Data available. Full preview will be loaded from the API when expanded.
            </Text>
          ),
        }))}
      />
    </div>
  );
}
