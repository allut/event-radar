import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/client';
import { API } from '../constants';
import { getLocale, setLocale, isAuthenticated } from '../lib/auth';

export interface UseLocaleMutationResult {
  locale: string;
  handleLocaleChange: (code: string) => void;
  isPending: boolean;
}

/**
 * Locale switcher backed by PATCH /users/me, shared by Feed, Explore, Saved,
 * EventDetail and Settings. Optimistically updates local state, persists on
 * success, reverts to the stored locale on failure. Server-localized queries
 * carry `locale` in their own query key + request param, so switching locale
 * naturally refetches (and separately caches) each page's content — no
 * cross-query invalidation needed here.
 */
export function useLocaleMutation(
  callbacks?: { onSuccess?: () => void; onError?: (err: unknown) => void },
): UseLocaleMutationResult {
  const [locale, setLocaleState] = useState(getLocale());

  const mutation = useMutation({
    mutationFn: (code: string) => api.patch(API.me, { locale: code }),
    onSuccess: (_data, code) => {
      setLocale(code);
      callbacks?.onSuccess?.();
    },
    onError: (err) => {
      setLocaleState(getLocale());
      callbacks?.onError?.(err);
    },
  });

  function handleLocaleChange(code: string) {
    setLocaleState(code);
    // Anonymous visitors (public EventDetail) have no session to persist
    // locale to — PATCH /users/me would 401 and trigger the client's
    // hard redirect to /login. Persist locally only in that case.
    if (!isAuthenticated()) {
      setLocale(code);
      callbacks?.onSuccess?.();
      return;
    }
    mutation.mutate(code);
  }

  return { locale, handleLocaleChange, isPending: mutation.isPending };
}
