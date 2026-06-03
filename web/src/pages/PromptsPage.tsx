import { useState } from 'react';
import { Card, Row, Col, Typography, Alert } from 'antd';
import PromptListPanel from '../components/prompts/PromptListPanel';
import PromptEditor from '../components/prompts/PromptEditor';
import { usePrompts } from '../hooks/usePrompts';
import type { PromptMeta } from '../types/prompt';

const { Title, Paragraph } = Typography;

export default function PromptsPage() {
  const { prompts, refresh: refreshPrompts } = usePrompts();
  const [selectedPrompt, setSelectedPrompt] = useState<PromptMeta | null>(null);

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', paddingTop: 24 }}>
      <Title level={3} style={{ marginBottom: 8 }}>提示词管理</Title>
      <Paragraph type="secondary" style={{ marginBottom: 16 }}>
        在此修改各 Agent 使用的提示词模板。修改保存后，将在下次创建的任务中生效。
      </Paragraph>

      <Alert
        message="提示词修改说明"
        description="修改后的提示词不会影响正在运行的任务。如需对当前任务生效，请在任务详情的流程步骤中点击「修改并重跑」。"
        type="info"
        showIcon
        style={{ marginBottom: 24 }}
      />

      <Row gutter={16}>
        <Col span={10}>
          <Card title="提示词列表" size="small">
            <PromptListPanel
              prompts={prompts}
              selectedKey={
                selectedPrompt
                  ? `${selectedPrompt.agent}/${selectedPrompt.name}`
                  : null
              }
              onSelect={setSelectedPrompt}
            />
          </Card>
        </Col>
        <Col span={14}>
          {selectedPrompt ? (
            <PromptEditor prompt={selectedPrompt} onSaved={refreshPrompts} />
          ) : (
            <Card
              style={{
                height: 500,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Typography.Text type="secondary">
                从左侧列表选择一个提示词进行编辑
              </Typography.Text>
            </Card>
          )}
        </Col>
      </Row>
    </div>
  );
}
