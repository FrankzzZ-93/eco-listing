import { useState } from 'react';
import { Card, Button, Space, Alert, Input, Typography, Divider, message } from 'antd';
import { EditOutlined } from '@ant-design/icons';
import AttributesSectionEditor from './AttributesSectionEditor';
import FullMarkdownEditor from './FullMarkdownEditor';
import { submitReview } from '../../api/runs';
import type { PendingAction } from '../../types/run';

const { Text } = Typography;
const { TextArea } = Input;

interface Props {
  runId: string;
  pendingAction: PendingAction | null;
  onReviewComplete: () => void;
}

const SECTIONS = [
  'target_users',
  'use_cases',
  'pain_points',
  'core_features',
  'selling_points',
  'language_patterns',
] as const;

const SECTION_LABELS: Record<string, string> = {
  target_users: 'Target Users',
  use_cases: 'Use Cases',
  pain_points: 'Pain Points',
  core_features: 'Core Features',
  selling_points: 'Selling Points',
  language_patterns: 'Language Patterns',
};

function serializeArray(val: unknown): string {
  if (Array.isArray(val)) return val.join('\n');
  if (typeof val === 'string') return val;
  return JSON.stringify(val, null, 2);
}

function parseArray(str: string): string[] {
  return str
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function AttributesReviewPanel({
  runId,
  pendingAction,
  onReviewComplete,
}: Props) {
  const [editorOpen, setEditorOpen] = useState(false);
  const [rejectMode, setRejectMode] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [loading, setLoading] = useState(false);

  const data = (pendingAction?.data?.product_attributes_draft ?? {}) as Record<string, unknown>;

  const [editedData, setEditedData] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    SECTIONS.forEach((key) => {
      init[key] = serializeArray(data[key]);
    });
    return init;
  });

  if (!pendingAction || pendingAction.type !== 'review_product_attributes') {
    return (
      <Card>
        <Alert
          message="No review action pending"
          description="The pipeline is running or has completed. Check the Status tab for progress."
          type="info"
          showIcon
        />
      </Card>
    );
  }

  const handleApprove = async (withEdits: boolean) => {
    setLoading(true);
    try {
      const approved: Record<string, string[]> = {};
      SECTIONS.forEach((key) => {
        approved[key] = parseArray(editedData[key]);
      });

      await submitReview(runId, {
        type: 'product_attributes',
        approved_data: approved,
      });
      message.success('Review submitted');
      onReviewComplete();
    } catch {
      message.error('Failed to submit review');
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    setLoading(true);
    try {
      await submitReview(runId, {
        type: 'product_attributes',
        approved_data: {},
        feedback,
      });
      message.success('Rejected, agent will re-generate');
      onReviewComplete();
    } catch {
      message.error('Failed to submit rejection');
    } finally {
      setLoading(false);
    }
  };

  const fullContent = SECTIONS.map(
    (key) => `## ${SECTION_LABELS[key]}\n${editedData[key]}`
  ).join('\n\n');

  const handleFullEditorSave = (content: string) => {
    const sectionRegex = /^## (.+)$/gm;
    const parts = content.split(sectionRegex).slice(1);
    for (let i = 0; i < parts.length; i += 2) {
      const title = parts[i].trim();
      const body = (parts[i + 1] ?? '').trim();
      const key = Object.entries(SECTION_LABELS).find(
        ([, label]) => label === title
      )?.[0];
      if (key) {
        setEditedData((prev) => ({ ...prev, [key]: body }));
      }
    }
    setEditorOpen(false);
  };

  return (
    <Card>
      <Text strong style={{ fontSize: 16 }}>
        Product Attributes Review
      </Text>

      {pendingAction.agent_notes && (
        <Alert
          message="Agent Notes"
          description={pendingAction.agent_notes}
          type="info"
          showIcon
          style={{ marginTop: 12, marginBottom: 16 }}
        />
      )}

      <Divider style={{ margin: '16px 0' }} />

      {SECTIONS.map((key) => (
        <AttributesSectionEditor
          key={key}
          label={SECTION_LABELS[key]}
          value={editedData[key]}
          onChange={(val) => setEditedData((prev) => ({ ...prev, [key]: val }))}
        />
      ))}

      <Divider style={{ margin: '16px 0' }} />

      <Space wrap>
        <Button icon={<EditOutlined />} onClick={() => setEditorOpen(true)}>
          Edit in Full Editor
        </Button>
      </Space>

      <Divider style={{ margin: '16px 0' }} />

      {rejectMode ? (
        <div>
          <TextArea
            placeholder="Optional feedback for the agent..."
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={3}
            style={{ marginBottom: 12 }}
          />
          <Space>
            <Button danger loading={loading} onClick={handleReject}>
              Confirm Reject
            </Button>
            <Button onClick={() => setRejectMode(false)}>Cancel</Button>
          </Space>
        </div>
      ) : (
        <Space>
          <Button type="primary" loading={loading} onClick={() => handleApprove(false)}>
            Approve
          </Button>
          <Button loading={loading} onClick={() => handleApprove(true)}>
            Approve with Edits
          </Button>
          <Button danger onClick={() => setRejectMode(true)}>
            Reject
          </Button>
        </Space>
      )}

      <FullMarkdownEditor
        open={editorOpen}
        content={fullContent}
        onSave={handleFullEditorSave}
        onClose={() => setEditorOpen(false)}
      />
    </Card>
  );
}
