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
