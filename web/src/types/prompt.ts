export interface PromptMeta {
  agent: string;
  name: string;
  filename: string;
  modified: boolean;
}

export interface PromptContent {
  agent: string;
  name: string;
  content: string;
  modified: boolean;
}
