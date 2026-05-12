import client from './client';
import type { PromptMeta, PromptContent } from '../types/prompt';

export async function listPrompts(): Promise<PromptMeta[]> {
  const res = await client.get<PromptMeta[]>('/prompts');
  return res.data;
}

export async function getPrompt(agent: string, name: string): Promise<PromptContent> {
  const res = await client.get<PromptContent>(`/prompts/${agent}/${name}`);
  return res.data;
}

export async function updatePrompt(agent: string, name: string, content: string): Promise<void> {
  await client.put(`/prompts/${agent}/${name}`, { content });
}

export async function resetPrompt(agent: string, name: string): Promise<void> {
  await client.delete(`/prompts/${agent}/${name}`);
}
