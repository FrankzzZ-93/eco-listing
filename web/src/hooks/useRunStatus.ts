import useSWR from 'swr';
import { getRun } from '../api/runs';
import type { RunDetail } from '../types/run';

export function useRunStatus(runId: string | undefined) {
  const { data, error, isLoading, mutate } = useSWR<RunDetail>(
    runId ? `/runs/${runId}` : null,
    () => getRun(runId!),
    {
      refreshInterval: 3000,
      revalidateOnFocus: false,
    }
  );

  const isTerminal = data?.status === 'completed' || data?.status === 'failed';

  return {
    run: data,
    error,
    isLoading,
    isTerminal,
    refresh: mutate,
  };
}
