import { useSyncExternalStore } from 'react';
import { getLocale, subscribeLocale } from '../lib/auth';

/** Live locale subscription, mirroring useAuth(). The globally mounted Footer
 * reads locale through this so a locale switch on any page re-renders it,
 * rather than reading getLocale() once at mount and going stale. */
export function useLocale(): string {
  return useSyncExternalStore(subscribeLocale, getLocale, getLocale);
}
