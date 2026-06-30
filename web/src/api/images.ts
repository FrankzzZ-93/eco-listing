import client from './client';

export interface RefImage {
  name: string;
  url: string; // same-origin /artifacts/... (proxied to backend)
}

export interface CompetitorImageGroup {
  asin: string;
  images: RefImage[];
}

export type ImageJobStatus = 'running' | 'completed' | 'failed';

export interface ImageJob {
  id: string;
  status: ImageJobStatus;
  prompt: string;
  n: number;
  size: string;
  quality: string;
  white_bg: boolean;
  reference_urls: string[];
  images: string[]; // result image URLs
  error: string | null;
  error_log?: string | null; // /artifacts URL of a full failure report (when failed)
  created_at: number;
  updated_at: number;
}

export interface GenerateImagesParams {
  prompt: string;
  n?: number;
  size?: string;
  quality?: string;
  referenceUrls?: string[];
  whiteBg?: boolean;
}

// Generation kicks off a background job and returns immediately; the job runs
// 1-3 min and the client polls listJobs. This request itself is quick.
export async function startGeneration(runId: string, params: GenerateImagesParams): Promise<ImageJob> {
  const res = await client.post<{ job: ImageJob }>(`/runs/${runId}/images/generate`, {
    prompt: params.prompt,
    n: params.n ?? 1,
    size: params.size ?? '1024x1024',
    quality: params.quality ?? 'high',
    reference_urls: params.referenceUrls ?? [],
    white_bg: params.whiteBg ?? false,
  });
  return res.data.job;
}

export async function listJobs(runId: string): Promise<ImageJob[]> {
  const res = await client.get<{ jobs: ImageJob[] }>(`/runs/${runId}/images/jobs`);
  return res.data.jobs;
}

export async function listCompetitorImages(runId: string): Promise<CompetitorImageGroup[]> {
  const res = await client.get<{ competitors: CompetitorImageGroup[] }>(`/runs/${runId}/competitor-images`);
  return res.data.competitors;
}

export async function uploadReferenceImage(runId: string, file: File): Promise<RefImage> {
  const form = new FormData();
  form.append('file', file);
  const res = await client.post<RefImage>(`/runs/${runId}/images/upload-reference`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}

export function imagesZipUrl(runId: string): string {
  return `/api/runs/${runId}/images/export.zip`;
}

/** Basename of an /artifacts image URL, for download filenames and keys. */
export function urlBasename(url: string): string {
  return url.split('/').pop() || url;
}
