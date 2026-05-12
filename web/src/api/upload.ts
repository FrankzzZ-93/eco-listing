import client from './client';

export async function uploadKeywordFile(runId: string, file: File): Promise<{ keyword_count: number }> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await client.put<{ keyword_count: number }>(`/runs/${runId}/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}
