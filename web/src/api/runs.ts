import client from './client';
import type { CreateRunRequest, CreateRunResponse, RunDetail, ReviewSubmission } from '../types/run';
import type { FinalOutput } from '../types/listing';

export async function createRun(data: CreateRunRequest): Promise<CreateRunResponse> {
  const res = await client.post<CreateRunResponse>('/runs', data);
  return res.data;
}

export async function getRun(runId: string): Promise<RunDetail> {
  const res = await client.get<RunDetail>(`/runs/${runId}`);
  return res.data;
}

export async function submitReview(runId: string, review: ReviewSubmission): Promise<void> {
  await client.put(`/runs/${runId}/review`, review);
}

export async function getFinal(runId: string): Promise<FinalOutput> {
  const res = await client.get<FinalOutput>(`/runs/${runId}/final`);
  return res.data;
}
