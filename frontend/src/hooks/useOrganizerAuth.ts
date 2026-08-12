import { useSyncExternalStore } from 'react';
import { isAuthenticatedOrganizer, subscribeOrganizerAuth } from '../lib/organizerAuth';

export function useOrganizerAuth(): boolean {
  return useSyncExternalStore(subscribeOrganizerAuth, isAuthenticatedOrganizer, isAuthenticatedOrganizer);
}
