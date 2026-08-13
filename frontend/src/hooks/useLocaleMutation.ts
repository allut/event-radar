import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { API, LOCALE_ET } from '../constants';
import { getStoredLocale, setLocale, isAuthenticated } from '../lib/auth';
import { localizedPath } from '../utils';
import { useRouteLocale } from './useRouteLocale';

export interface UseLocaleMutationResult {
  locale: string;
  handleLocaleChange: (code: string) => void;
  isPending: boolean;
}

export interface UseLocaleMutationCallbacks {
  onSuccess?: () => void;
  onError?: (err: unknown) => void;
  // Home/Landing/Feed and EventDetail are the two public SEO routes (see
  // App.tsx's ROUTE_DEFS): their bare path must always render Estonian
  // regardless of any stored preference, so their initial locale resolves
  // purely from the URL's `:locale` segment. Every other page falls back to
  // the explicitly *stored* preference (getStoredLocale(), not getLocale()'s
  // UI-default fallback of 'en') when no segment is present, defaulting to
  // Estonian when nothing is stored — matching App.tsx's BareLocaleGate,
  // which only redirects a bare path when a non-Estonian preference was
  // explicitly stored, leaving both "no preference" and "explicitly et" on
  // the bare path.
  publicRoute?: boolean;
}

/**
 * Locale switcher backed by PATCH /users/me, shared by Feed, Explore, Saved,
 * EventDetail, Landing and Settings. The initial locale resolves from the
 * URL's `:locale` segment when present, else from the stored preference (or
 * Estonian for `publicRoute` callers). Switching locale updates optimistically,
 * navigates to the equivalent path under the new prefix, and persists via
 * localStorage/PATCH — reverting the optimistic value on a failed PATCH.
 */
export function useLocaleMutation(
  callbacks?: UseLocaleMutationCallbacks,
): UseLocaleMutationResult {
  const { locale: urlLocale } = useParams<{ locale?: string }>();
  const routeLocale = useRouteLocale();
  const navigate = useNavigate();
  const location = useLocation();

  function resolveLocale(): string {
    if (urlLocale || callbacks?.publicRoute) return routeLocale;
    return getStoredLocale() ?? LOCALE_ET;
  }

  const [locale, setLocaleState] = useState(resolveLocale);

  // Keeps `locale` in sync when the matched route's `:locale` segment
  // changes without necessarily remounting this component — react-router can
  // reuse the same element across two different Route matches at the same
  // tree position (e.g. Home's bare "/" and "/:locale" registrations), which
  // would otherwise leave the useState initializer's stale value in place.
  // Adjusting state during render (React's documented pattern for this,
  // rather than an effect) avoids an extra post-paint render pass.
  const [prevUrlLocale, setPrevUrlLocale] = useState(urlLocale);
  if (urlLocale !== prevUrlLocale) {
    setPrevUrlLocale(urlLocale);
    setLocaleState(resolveLocale());
  }

  const mutation = useMutation({
    mutationFn: (code: string) => api.patch(API.me, { locale: code }),
  });

  function handleLocaleChange(code: string) {
    setLocaleState(code);
    navigate(localizedPath(location.pathname, code) + location.search, { replace: false });
    // Anonymous visitors (public EventDetail) have no session to persist
    // locale to — PATCH /users/me would 401 and trigger the client's
    // hard redirect to /login. Persist locally only in that case.
    if (!isAuthenticated()) {
      setLocale(code);
      callbacks?.onSuccess?.();
      return;
    }
    mutation.mutate(code, {
      onSuccess: () => {
        setLocale(code);
        callbacks?.onSuccess?.();
      },
      onError: (err) => {
        setLocaleState(resolveLocale());
        callbacks?.onError?.(err);
      },
    });
  }

  return { locale, handleLocaleChange, isPending: mutation.isPending };
}
