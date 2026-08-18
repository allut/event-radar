import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { organizerApi } from '../api/client';
import { API, ROUTES } from '../constants';
import { beginOrganizerLogout, clearOrganizerSignedInHint } from '../lib/organizerAuth';
import { useLocaleNavigate } from './useLocaleNavigate';

export function useOrganizerLogout(): () => void {
  const navigate = useLocaleNavigate();
  const queryClient = useQueryClient();
  return useCallback(() => {
    beginOrganizerLogout();
    // Best-effort: a failed network call must not strand the organizer signed
    // in locally, so the local hint clear/navigation below don't wait on it.
    void organizerApi.post(API.organizerAuthLogout).catch(() => undefined);
    clearOrganizerSignedInHint();
    queryClient.clear();
    navigate(ROUTES.organizerLogin, { replace: true });
  }, [navigate, queryClient]);
}
