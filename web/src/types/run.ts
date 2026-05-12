export type RunStatus = 'running' | 'waiting_human' | 'completed' | 'failed';

export type AgentName = 'research' | 'product_analyst' | 'keyword_strategist' | 'copywriter' | 'orchestrator';

export interface AgentLog {
  agent: AgentName;
  action: string;
  input_keys?: string[];
  output_keys?: string[];
  model?: string;
  tokens?: number;
  duration_ms: number;
  timestamp: string;
  status?: 'ok' | 'error' | 'waiting';
}

export interface MemorySnapshot {
  has_competitor_listings: boolean;
  has_review_summary: boolean;
  has_rufus_questions: boolean;
  has_product_attributes_draft: boolean;
  has_approved_product_attributes: boolean;
  has_classified_keywords: boolean;
  has_final_listing: boolean;
  has_final_st: boolean;
}

export interface PendingAction {
  type: 'review_product_attributes' | 'review_listing_draft';
  data: Record<string, unknown>;
  agent_notes?: string;
}

export interface RunDetail {
  run_id: string;
  status: RunStatus;
  current_agent: AgentName | null;
  memory_snapshot: MemorySnapshot;
  pending_action: PendingAction | null;
  agent_log: AgentLog[];
}

export interface CreateRunRequest {
  product_name?: string;
  competitor_asins: string[];
  site: string;
}

export interface CreateRunResponse {
  run_id: string;
}

export interface ReviewSubmission {
  type: string;
  approved_data: Record<string, unknown>;
  feedback?: string;
}
