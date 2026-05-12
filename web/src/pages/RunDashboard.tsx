import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Layout, Tabs, Card, Spin, Typography, Row, Col } from 'antd';
import PipelineSidebar from '../components/pipeline/PipelineSidebar';
import AgentLogTable from '../components/status/AgentLogTable';
import DataPreviewCollapse from '../components/status/DataPreviewCollapse';
import AttributesReviewPanel from '../components/review/AttributesReviewPanel';
import PromptListPanel from '../components/prompts/PromptListPanel';
import PromptEditor from '../components/prompts/PromptEditor';
import ListingPreview from '../components/output/ListingPreview';
import { useRunStatus } from '../hooks/useRunStatus';
import { usePrompts } from '../hooks/usePrompts';
import { getFinal } from '../api/runs';
import type { PromptMeta } from '../types/prompt';
import type { FinalOutput } from '../types/listing';

const { Sider, Content } = Layout;
const { Title } = Typography;

export default function RunDashboard() {
  const { runId, tab } = useParams<{ runId: string; tab?: string }>();
  const navigate = useNavigate();
  const { run, isLoading } = useRunStatus(runId);
  const { prompts, refresh: refreshPrompts } = usePrompts();

  const [activeTab, setActiveTab] = useState(tab || 'status');
  const [selectedPrompt, setSelectedPrompt] = useState<PromptMeta | null>(null);
  const [finalOutput, setFinalOutput] = useState<FinalOutput | null>(null);
  const [finalLoading, setFinalLoading] = useState(false);

  useEffect(() => {
    if (tab) setActiveTab(tab);
  }, [tab]);

  useEffect(() => {
    if (run?.status === 'waiting_human') {
      setActiveTab('review');
    }
  }, [run?.status]);

  useEffect(() => {
    if (run?.memory_snapshot?.has_final_listing && run?.memory_snapshot?.has_final_st) {
      setFinalLoading(true);
      getFinal(runId!)
        .then(setFinalOutput)
        .catch(() => {})
        .finally(() => setFinalLoading(false));
    }
  }, [run?.memory_snapshot?.has_final_listing, run?.memory_snapshot?.has_final_st, runId]);

  const handleTabChange = (key: string) => {
    setActiveTab(key);
    navigate(`/run/${runId}/${key}`, { replace: true });
  };

  if (isLoading && !run) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 100 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <Layout style={{ background: 'transparent', minHeight: 'calc(100vh - 130px)' }}>
      <Sider
        width={220}
        style={{
          background: '#fff',
          borderRadius: 8,
          marginRight: 16,
          overflow: 'auto',
        }}
      >
        <PipelineSidebar run={run} />
      </Sider>

      <Content>
        <Card style={{ minHeight: 500 }}>
          <Tabs
            activeKey={activeTab}
            onChange={handleTabChange}
            items={[
              {
                key: 'status',
                label: 'Status',
                children: (
                  <div>
                    <Title level={5}>Agent Log</Title>
                    <AgentLogTable logs={run?.agent_log ?? []} />
                    <div style={{ marginTop: 24 }}>
                      <DataPreviewCollapse memorySnapshot={run?.memory_snapshot} />
                    </div>
                  </div>
                ),
              },
              {
                key: 'review',
                label: 'Review',
                children: (
                  <AttributesReviewPanel
                    runId={runId!}
                    pendingAction={run?.pending_action ?? null}
                    onReviewComplete={() => {}}
                  />
                ),
              },
              {
                key: 'prompts',
                label: 'Prompts',
                children: (
                  <Row gutter={16}>
                    <Col span={10}>
                      <PromptListPanel
                        prompts={prompts}
                        selectedKey={
                          selectedPrompt
                            ? `${selectedPrompt.agent}/${selectedPrompt.name}`
                            : null
                        }
                        onSelect={setSelectedPrompt}
                      />
                    </Col>
                    <Col span={14}>
                      {selectedPrompt ? (
                        <PromptEditor
                          prompt={selectedPrompt}
                          onSaved={refreshPrompts}
                        />
                      ) : (
                        <Card style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <Typography.Text type="secondary">
                            Select a prompt from the list to edit
                          </Typography.Text>
                        </Card>
                      )}
                    </Col>
                  </Row>
                ),
              },
              {
                key: 'output',
                label: 'Output',
                children: (
                  <ListingPreview output={finalOutput} loading={finalLoading} />
                ),
              },
            ]}
          />
        </Card>
      </Content>
    </Layout>
  );
}
