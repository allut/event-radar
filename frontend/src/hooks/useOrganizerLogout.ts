import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { organizerApi } from '../api/client';
import { beginOrganizerLogout, clearOrganizerSignedInHint } from '../lib/organizerAuth';

export function useOrganizerLogout(): () => void {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  return useCallback(() => {
    beginOrganizerLogout();
    // Best-effort: a failed network call must not strand the organizer signed
    // in locally, so the local hint clear/navigation below don't wait on it.
    void organizerApi.post('/organizer/auth/logout').catch(() => undefined);
    clearOrganizerSignedInHint();
    queryClient.clear();
    navigate('/organizer/login', { replace: true });
  }, [navigate, queryClient]);
}
