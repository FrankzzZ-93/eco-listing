import client from './client';
import type { CreateRunRequest, CreateRunResponse, RunDetail, RunSummary, ReviewSubmission } from '../types/run';
import type { FinalOutput } from '../types/listing';

export async function createRun(data: CreateRunRequest): Promise<CreateRunResponse> {
  const res = await client.post<CreateRunResponse>('/runs', data);
  return res.data;
}

export async function listRuns(): Promise<RunSummary[]> {
  const res = await client.get<RunSummary[]>('/runs');
  return res.data;
}

export async function getRun(runId: string): Promise<RunDetail> {
  const res = await client.get<RunDetail>(`/runs/${runId}`);
  return res.data;
}

export async function submitReview(runId: string, review: ReviewSubmission): Promise<void> {
  await client.put(`/runs/${runId}/review`, review);
}

export async function uploadFile(
  runId: string,
  file: File,
  dataType: 'listings' | 'keywords' | 'reviews' | 'product_attributes' | 'auto' = 'auto',
): Promise<void> {
  const form = new FormData();
  form.append('file', file);
  await client.put(`/runs/${runId}/upload?data_type=${dataType}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
}

export async function getRunData(runId: string, key: string): Promise<{ key: string; data: unknown }> {
  const res = await client.get<{ key: string; data: unknown }>(`/runs/${runId}/data/${key}`);
  return res.data;
}

export async function startRun(runId: string): Promise<void> {
  await client.post(`/runs/${runId}/start`);
}

export async function submitKeywordReview(
  runId: string,
  approvedKeywords: Record<string, unknown>[],
): Promise<void> {
  await client.put(`/runs/${runId}/keyword-review`, { approved_keywords: approvedKeywords });
}

export async function pauseRun(runId: string): Promise<void> {
  await client.post(`/runs/${runId}/pause`);
}

export async function resumeRun(runId: string): Promise<void> {
  await client.post(`/runs/${runId}/resume`);
}

export async function stopRun(runId: string): Promise<void> {
  await client.post(`/runs/${runId}/stop`);
}

export async function deleteRun(runId: string): Promise<void> {
  await client.delete(`/runs/${runId}`);
}

export async function getFinal(runId: string): Promise<FinalOutput> {
  const res = await client.get<FinalOutput>(`/runs/${runId}/final`);
  return res.data;
}
