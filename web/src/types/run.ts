export type RunStatus = 'running' | 'waiting_human' | 'completed' | 'failed' | 'paused' | 'stopped' | 'pending';

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
  has_customer_reviews: boolean;
  has_review_summary: boolean;
  has_alex_questions: boolean;
  has_product_attributes_draft: boolean;
  has_approved_product_attributes: boolean;
  has_keyword_library: boolean;
  has_keywords_reviewed: boolean;
  has_classified_keywords: boolean;
  has_final_listing: boolean;
  has_final_st: boolean;
}

export interface PendingAction {
  type:
    | 'review_product_attributes'
    | 'upload_keywords'
    | 'review_classified_keywords'
    | 'review_listing_draft'
    | 'solve_captcha'
    | 'upload_competitor_data';
  data?: Record<string, unknown>;
  message?: string;
  agent_notes?: string;
  // Captcha gate only:
  image_url?: string;
  context?: 'scrape' | 'login';
}

export interface LiveCodexProgress {
  started_at: string;
  elapsed_s: number;
  current_event_type: string | null;
  items_completed: number;
  last_change_at: string;
}

export interface ResearchProgress {
  phase: string;
  done: number;
  total: number;
}

export interface StageProgress {
  label: string;
  step: number;
  total: number;
}

export interface RunDetail {
  run_id: string;
  product_name?: string;
  status: RunStatus;
  current_agent: AgentName | null;
  memory_snapshot: MemorySnapshot;
  pending_action: PendingAction | null;
  agent_log: AgentLog[];
  error: string | null;
  live_codex?: LiveCodexProgress | null;
  research_progress?: ResearchProgress | null;
  stage_progress?: StageProgress | null;
}

export interface CreateRunRequest {
  product_name?: string;
  competitor_asins: string[];
  site: string;
}

export interface CreateRunResponse {
  run_id: string;
}

export interface RunSummary {
  run_id: string;
  product_name: string;
  site: string;
  competitor_asins: string[];
  created_at: string;
  status: string;
  completed_steps: number;
  total_steps: number;
  current_step: string;
  current_agent: string | null;
}

export interface ReviewSubmission {
  type: string;
  approved_data: Record<string, unknown>;
  feedback?: string;
}
