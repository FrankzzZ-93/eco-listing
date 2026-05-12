import { useState } from 'react';
import { Card, Button, Space, Segmented, Empty, Typography } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import SectionCard from './SectionCard';
import CopyButton from './CopyButton';
import VerificationChecklist from './VerificationChecklist';
import { getByteLength, getCharLength } from '../../utils/byteCounter';
import type { FinalOutput } from '../../types/listing';

const { Text } = Typography;

interface Props {
  output: FinalOutput | null;
  loading: boolean;
}

export default function ListingPreview({ output, loading }: Props) {
  const [descView, setDescView] = useState<'preview' | 'source'>('preview');

  if (!output) {
    return <Empty description={loading ? 'Loading...' : 'Final listing not yet available'} />;
  }

  const { listing, verification } = output;
  const bulletsJoined = listing.bullet_points.join('\n');
  const bulletsBytes = getByteLength(bulletsJoined);

  return (
    <div>
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={
          <Text strong>
            Final Listing{output.product_name ? ` — ${output.product_name}` : ''} — {output.site}
          </Text>
        }
        extra={
          <Space>
            <Button size="small" icon={<DownloadOutlined />}>
              Download MD
            </Button>
            <Button size="small" icon={<DownloadOutlined />}>
              Download JSON
            </Button>
          </Space>
        }
      />

      <SectionCard
        title="Title"
        content={listing.title}
        currentCount={getCharLength(listing.title)}
        maxCount={200}
        unit="chars"
      />

      <SectionCard
        title="Bullet Points"
        content={bulletsJoined}
        currentCount={bulletsBytes}
        maxCount={1000}
        unit="bytes"
      >
        <div style={{ background: '#fafafa', padding: 12, borderRadius: 6 }}>
          {listing.bullet_points.map((bp, idx) => (
            <div
              key={idx}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                marginBottom: 8,
                fontFamily: 'monospace',
                fontSize: 13,
              }}
            >
              <span style={{ flex: 1, whiteSpace: 'pre-wrap' }}>
                {'\u2022'} {bp}
              </span>
              <CopyButton text={bp} />
            </div>
          ))}
        </div>
      </SectionCard>

      <Card
        size="small"
        title={
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Text strong>Description</Text>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {getCharLength(listing.description)} / 2000 chars
              </Text>
              <CopyButton text={listing.description} />
            </div>
          </div>
        }
        style={{ marginBottom: 16 }}
      >
        <Segmented
          size="small"
          options={[
            { label: 'Preview', value: 'preview' },
            { label: 'Source', value: 'source' },
          ]}
          value={descView}
          onChange={(val) => setDescView(val as 'preview' | 'source')}
          style={{ marginBottom: 12 }}
        />
        {descView === 'preview' ? (
          <div
            style={{ padding: 12, background: '#fafafa', borderRadius: 6 }}
            dangerouslySetInnerHTML={{ __html: listing.description }}
          />
        ) : (
          <div
            style={{
              padding: 12,
              background: '#fafafa',
              borderRadius: 6,
              whiteSpace: 'pre-wrap',
              fontFamily: 'monospace',
              fontSize: 13,
              maxHeight: 300,
              overflow: 'auto',
            }}
          >
            {listing.description}
          </div>
        )}
      </Card>

      <SectionCard
        title="Search Terms"
        content={listing.search_terms}
        currentCount={getByteLength(listing.search_terms)}
        maxCount={249}
        unit="bytes"
      />

      <VerificationChecklist items={verification} />
    </div>
  );
}
