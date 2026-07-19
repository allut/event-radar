import { useSyncExternalStore } from 'react';
import { isAuthenticated, subscribeAuth } from '../lib/auth';

export function useAuth(): boolean {
  return useSyncExternalStore(subscribeAuth, isAuthenticated, isAuthenticated);
}
