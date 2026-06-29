import { useEffect, useState } from 'react';
import { Image, Empty, Spin, Typography, Tag, Space } from 'antd';
import { getRunScreenshots, type ScrapeScreenshot } from '../../api/runs';

const { Text } = Typography;

const KIND_META: Record<string, { label: string; color: string }> = {
  reviews: { label: '评论', color: 'blue' },
  alex: { label: 'Alex/Rufus', color: 'purple' },
  verify: { label: '验证码', color: 'orange' },
};

/** Gallery of the scrape evidence screenshots (reviews / Alex / verification)
 *  captured by the real-Chrome engine, grouped by ASIN, for manual review.
 *  Pass `kind` to show only one type (e.g. 'reviews' next to the review data). */
export default function ScrapeScreenshots({
  runId,
  kind,
}: {
  runId: string;
  kind?: 'reviews' | 'alex' | 'verify';
}) {
  const [shots, setShots] = useState<ScrapeScreenshot[] | null>(null);

  useEffect(() => {
    let alive = true;
    getRunScreenshots(runId)
      .then((s) => { if (alive) setShots(s); })
      .catch(() => { if (alive) setShots([]); });
    return () => { alive = false; };
  }, [runId]);

  if (shots === null) return <Spin />;
  const visible = kind ? shots.filter((s) => s.kind === kind) : shots;
  if (visible.length === 0) {
    return <Empty description="暂无抓取截图" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  const groups = new Map<string, ScrapeScreenshot[]>();
  for (const s of visible) {
    const key = s.asin || '其他';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(s);
  }

  return (
    <Image.PreviewGroup>
      {Array.from(groups.entries()).map(([asin, items]) => (
        <div key={asin} style={{ marginBottom: 16 }}>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>{asin}</Text>
          <Space wrap size={[12, 12]}>
            {items.map((s) => (
              <div key={s.name} style={{ textAlign: 'center' }}>
                <Image
                  src={s.url}
                  width={150}
                  height={104}
                  style={{
                    objectFit: 'cover',
                    borderRadius: 6,
                    border: '1px solid var(--ant-color-border, #eee)',
                  }}
                />
                <div style={{ marginTop: 4 }}>
                  <Tag color={KIND_META[s.kind]?.color}>{KIND_META[s.kind]?.label ?? s.kind}</Tag>
                </div>
              </div>
            ))}
          </Space>
        </div>
      ))}
    </Image.PreviewGroup>
  );
}
