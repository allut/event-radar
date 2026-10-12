import { useCallback, useMemo } from 'react';
import { ROUTES } from '../constants/routes';
import { useAuth } from './useAuth';
import { useLocaleNavigate } from './useLocaleNavigate';
import { useLocalePath } from './useLocalePath';

/** Router/auth context an `EventCard` needs, resolved once by the parent list
 * instead of subscribed per card (issue #455). Memoized so one referentially
 * stable object goes to every card and `EventCard`'s `memo` still holds. */
export interface EventCardNav {
  localePath: (to: string) => string;
  authed: boolean;
  onLoginRequired: () => void;
}

export function useEventCardNav(): EventCardNav {
  const localePath = useLocalePath();
  const authed = useAuth();
  const navigate = useLocaleNavigate();
  const onLoginRequired = useCallback(() => navigate(ROUTES.login), [navigate]);
  return useMemo(() => ({ localePath, authed, onLoginRequired }), [localePath, authed, onLoginRequired]);
}
