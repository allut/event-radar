import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { adminApi } from '../api/client';
import { API } from '../constants/api';
import { ROUTES } from '../constants/routes';
import { beginAdminLogout, clearAdminSignedInHint } from '../lib/adminAuth';

// Mirrors useLogout/useOrganizerLogout, but navigates with plain useNavigate
// rather than useLocaleNavigate — the admin console has no i18n/locale
// concept (see AdminApp, registered outside App.tsx's locale-prefix loop).
export function useAdminLogout(): () => void {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  return useCallback(() => {
    beginAdminLogout();
    // Best-effort: a failed network call must not strand the admin signed in
    // locally, so the local hint clear/navigation below don't wait on it.
    void adminApi.post(API.adminAuthLogout).catch(() => undefined);
    clearAdminSignedInHint();
    queryClient.clear();
    navigate(ROUTES.adminLogin, { replace: true });
  }, [navigate, queryClient]);
}
