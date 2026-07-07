import { useState } from 'react';
import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { api } from '../api/client';
import { getLocale, setLocale } from '../lib/auth';

/**
 * Locale switcher backed by PATCH /users/me, shared by Feed, EventDetail and
 * Settings. Optimistically updates local state, persists on success (and
 * invalidates the given query key so localized content refetches), reverts to
 * the stored locale on failure.
 */
export function useLocaleMutation(
  invalidateKey: QueryKey,
  callbacks?: { onSuccess?: () => void; onError?: (err: unknown) => void },
) {
  const queryClient = useQueryClient();
  const [locale, setLocaleState] = useState(getLocale());

  const mutation = useMutation({
    mutationFn: (code: string) => api.patch('/users/me', { locale: code }),
    onSuccess: (_data, code) => {
      setLocale(code);
      queryClient.invalidateQueries({ queryKey: invalidateKey });
      callbacks?.onSuccess?.();
    },
    onError: (err) => {
      setLocaleState(getLocale());
      callbacks?.onError?.(err);
    },
  });

  function handleLocaleChange(code: string) {
    setLocaleState(code);
    mutation.mutate(code);
  }

  return { locale, handleLocaleChange, isPending: mutation.isPending };
}
