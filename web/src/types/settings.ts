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

// Listing length rules edited on the settings page. Minimums: 0 = not checked.
export interface ListingLimits {
  title_max_chars: number;
  item_highlights_max_chars: number;
  bullet_max_chars: number;
  bullets_total_max_bytes: number;
  description_max_chars: number;
  st_max_bytes: number;
  title_min_chars: number;
  bullets_total_min_bytes: number;
  description_min_chars: number;
}

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
  listing_limits: ListingLimits;
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
  listing_limits?: Partial<ListingLimits>;
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
