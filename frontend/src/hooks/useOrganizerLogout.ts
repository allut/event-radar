import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { beginOrganizerLogout, clearOrganizerToken } from '../lib/organizerAuth';

export function useOrganizerLogout(): () => void {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  return useCallback(() => {
    beginOrganizerLogout();
    clearOrganizerToken();
    queryClient.clear();
    navigate('/organizer/login', { replace: true });
  }, [navigate, queryClient]);
}
