import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { API, ROUTES } from '../constants';
import { beginLogout, clearSignedInHint } from '../lib/auth';
import { useLocaleNavigate } from './useLocaleNavigate';

export function useLogout(): () => void {
  const navigate = useLocaleNavigate();
  const queryClient = useQueryClient();
  return useCallback(() => {
    beginLogout();
    // Best-effort: a failed network call must not strand the user signed in
    // locally, so the local hint clear/navigation below don't wait on it.
    void api.post(API.authLogout).catch(() => undefined);
    clearSignedInHint();
    queryClient.clear();
    navigate(ROUTES.home, { replace: true });
  }, [navigate, queryClient]);
}
