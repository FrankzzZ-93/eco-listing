import useSWR from 'swr';
import { listPrompts } from '../api/prompts';
import type { PromptMeta } from '../types/prompt';

export function usePrompts() {
  const { data, error, isLoading, mutate } = useSWR<PromptMeta[]>(
    '/prompts',
    listPrompts,
    { revalidateOnFocus: false }
  );

  return {
    prompts: data ?? [],
    error,
    isLoading,
    refresh: mutate,
  };
}
