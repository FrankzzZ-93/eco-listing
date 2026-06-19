import client from './client';
import type {
  LlmSettings,
  LlmSettingsUpdate,
  LlmTestResult,
  AppSettings,
  AppSettingsUpdate,
} from '../types/settings';

export async function getLlmSettings(): Promise<LlmSettings> {
  const res = await client.get<LlmSettings>('/settings/llm');
  return res.data;
}

export async function updateLlmSettings(payload: LlmSettingsUpdate): Promise<LlmSettings> {
  const res = await client.put<LlmSettings>('/settings/llm', payload);
  return res.data;
}

export async function testLlmSettings(payload: LlmSettingsUpdate): Promise<LlmTestResult> {
  const res = await client.post<LlmTestResult>('/settings/llm/test', payload);
  return res.data;
}

export async function getAppSettings(): Promise<AppSettings> {
  const res = await client.get<AppSettings>('/settings/app');
  return res.data;
}

export async function updateAppSettings(payload: AppSettingsUpdate): Promise<AppSettings> {
  const res = await client.put<AppSettings>('/settings/app', payload);
  return res.data;
}
