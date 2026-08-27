import { useSyncExternalStore } from 'react';
import { isAuthenticatedAdmin, subscribeAdminAuth } from '../lib/adminAuth';

export function useAdminAuth(): boolean {
  return useSyncExternalStore(subscribeAdminAuth, isAuthenticatedAdmin, isAuthenticatedAdmin);
}
