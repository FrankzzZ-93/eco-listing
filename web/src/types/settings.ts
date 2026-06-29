export type LlmProvider = 'codex-cli' | 'openai_compatible';

export interface LlmSettings {
  provider: LlmProvider;
  base_url: string;
  model: string;
  api_key_set: boolean;
  api_key_hint: string;
}

export interface LlmSettingsUpdate {
  provider: LlmProvider;
  base_url?: string;
  model?: string;
  // Omit/empty to keep the stored key unchanged.
  api_key?: string;
}

export interface LlmTestResult {
  ok: boolean;
  message: string;
}

export type ReviewEngine = 'real_chrome' | 'builtin';

export interface AppSettings {
  account: {
    site: string;
    email: string;
    password_set: boolean;
    proxy_region: string;
  };
  scrape: {
    browser_headless: boolean;
    scrape_max_review_pages: number;
    research_concurrency: number;
    codex_timeout: number;
  };
  review_engine: ReviewEngine;
}

export interface AppSettingsUpdate {
  account?: {
    site?: string;
    email?: string;
    // Omit/empty to keep the stored password unchanged.
    password?: string;
    proxy_region?: string;
  };
  scrape?: Partial<AppSettings['scrape']>;
  review_engine?: ReviewEngine;
}

export type AccountState =
  | 'idle'
  | 'opening'
  | 'waiting_manual'
  | 'logged_in'
  | 'failed'
  | 'unavailable';

export interface AccountStatus {
  available: boolean;
  state: AccountState;
  message: string;
  image_url: string;
  updated_at: string;
  account_email: string;
}
