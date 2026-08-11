import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { beginLogout, clearSignedInHint } from '../lib/auth';

export function useLogout(): () => void {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  return useCallback(() => {
    beginLogout();
    // Best-effort: a failed network call must not strand the user signed in
    // locally, so the local hint clear/navigation below don't wait on it.
    void api.post('/auth/logout').catch(() => undefined);
    clearSignedInHint();
    queryClient.clear();
    navigate('/', { replace: true });
  }, [navigate, queryClient]);
}
