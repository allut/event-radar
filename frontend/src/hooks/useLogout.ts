import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { beginLogout, clearToken } from '../lib/auth';

export function useLogout(): () => void {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  return useCallback(() => {
    beginLogout();
    clearToken();
    queryClient.clear();
    navigate('/', { replace: true });
  }, [navigate, queryClient]);
}
