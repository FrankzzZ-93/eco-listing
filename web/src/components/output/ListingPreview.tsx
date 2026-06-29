import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Button, Space, Segmented, Empty, Typography, Descriptions, Tag, Popconfirm, message } from 'antd';
import { DownloadOutlined, ReloadOutlined, PictureOutlined } from '@ant-design/icons';
import SectionCard from './SectionCard';
import CopyButton from './CopyButton';
import { getByteLength, getCharLength } from '../../utils/byteCounter';
import { downloadUrlAsFile } from '../../utils/download';
import type { FinalOutput } from '../../types/listing';

const { Text } = Typography;

interface Props {
  output: FinalOutput | null;
  loading: boolean;
  runId?: string;
  canRegenerate?: boolean;
  regenerating?: boolean;
  onRegenerate?: () => void;
}

function joinSearchTerms(terms: string[]): string {
  return terms.join(' ');
}

function makeAbsolute(path: string | undefined): string | undefined {
  if (!path) return undefined;
  if (/^https?:\/\//.test(path)) return path;
  return path.startsWith('/') ? path : `/${path}`;
}

export default function ListingPreview({ output, loading, runId, canRegenerate, regenerating, onRegenerate }: Props) {
  const [descView, setDescView] = useState<'preview' | 'source'>('preview');
  const navigate = useNavigate();

  if (!output) {
    return <Empty description={loading ? '加载中…' : '最终 Listing 尚未生成'} />;
  }

  const listing = output.final_listing;
  const finalSt = output.final_st ?? [];
  const report = output.word_frequency_report;
  const download = output.download;

  if (!listing) {
    return <Empty description="最终 Listing 数据缺失" />;
  }

  const bullets = listing.bullet_points ?? [];
  const bulletsJoined = bullets.join('\n');
  const bulletsBytes = getByteLength(bulletsJoined);
  const searchTermsStr = joinSearchTerms(finalSt);

  const mdHref = makeAbsolute(download?.markdown);
  const jsonHref = makeAbsolute(download?.json);
  const namePrefix = runId ? `${runId}_listing` : 'final_listing';

  const handleDownload = async (href: string | undefined, filename: string) => {
    if (!href) return;
    try {
      // Cache-bust so a regenerated file isn't served from a stale cache.
      await downloadUrlAsFile(`${href}?t=${Date.now()}`, filename);
    } catch {
      message.error('下载失败，请重试');
    }
  };

  return (
    <div>
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        title={<Text strong>最终 Listing</Text>}
        extra={
          <Space>
            {runId && (
              <Button
                size="small"
                type="primary"
                ghost
                icon={<PictureOutlined />}
                onClick={() => navigate(`/run/${runId}/images`)}
              >
                生成商品图
              </Button>
            )}
            {onRegenerate && (
              <Popconfirm
                title="重新生成 Listing 文案？"
                description="将使用最新的产品属性表、关键词分类表、模型与提示词重写文案（不会重新抓取竞品）。"
                okText="重新生成"
                cancelText="取消"
                disabled={!canRegenerate || regenerating}
                onConfirm={onRegenerate}
              >
                <Button
                  size="small"
                  type="primary"
                  icon={<ReloadOutlined />}
                  loading={regenerating}
                  disabled={!canRegenerate}
                >
                  重新生成文案
                </Button>
              </Popconfirm>
            )}
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => handleDownload(mdHref, `${namePrefix}.md`)}
              disabled={!mdHref}
            >
              下载 MD
            </Button>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => handleDownload(jsonHref, `${namePrefix}.json`)}
              disabled={!jsonHref}
            >
              下载 JSON
            </Button>
          </Space>
        }
      >
        {report && (
          <Descriptions size="small" column={4} bordered>
            <Descriptions.Item label="关键词总数">{report.total_keywords}</Descriptions.Item>
            <Descriptions.Item label="文案中使用">{report.used_in_listing}</Descriptions.Item>
            <Descriptions.Item label="加入 ST">{report.added_to_st}</Descriptions.Item>
            <Descriptions.Item label="ST 字节">
              <Tag color={report.total_bytes > 249 ? 'red' : 'green'}>{report.total_bytes} / 249</Tag>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Card>

      <SectionCard
        title="标题 (Title)"
        content={listing.title ?? ''}
        currentCount={getCharLength(listing.title ?? '')}
        maxCount={200}
        unit="字符"
      />

      <SectionCard
        title="五点描述 (Bullet Points)"
        content={bulletsJoined}
        currentCount={bulletsBytes}
        maxCount={1000}
        unit="字节"
      >
        <div style={{ background: '#fafafa', padding: 12, borderRadius: 6 }}>
          {bullets.map((bp, idx) => (
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
            <Text strong>产品描述 (Description)</Text>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {getCharLength(listing.description ?? '')} / 2000 字符
              </Text>
              <CopyButton text={listing.description ?? ''} />
            </div>
          </div>
        }
        style={{ marginBottom: 16 }}
      >
        <Segmented
          size="small"
          options={[
            { label: '预览', value: 'preview' },
            { label: '源码', value: 'source' },
          ]}
          value={descView}
          onChange={(val) => setDescView(val as 'preview' | 'source')}
          style={{ marginBottom: 12 }}
        />
        {descView === 'preview' ? (
          <div
            style={{ padding: 12, background: '#fafafa', borderRadius: 6 }}
            dangerouslySetInnerHTML={{ __html: listing.description ?? '' }}
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
            {listing.description ?? ''}
          </div>
        )}
      </Card>

      <SectionCard
        title="Search Terms"
        content={searchTermsStr}
        currentCount={getByteLength(searchTermsStr)}
        maxCount={249}
        unit="字节"
      >
        <div style={{ background: '#fafafa', padding: 12, borderRadius: 6 }}>
          {finalSt.length === 0 ? (
            <Text type="secondary">暂无 Search Terms</Text>
          ) : (
            <Space size={[4, 4]} wrap>
              {finalSt.map((term, idx) => (
                <Tag key={idx}>{term}</Tag>
              ))}
            </Space>
          )}
        </div>
      </SectionCard>
    </div>
  );
}
