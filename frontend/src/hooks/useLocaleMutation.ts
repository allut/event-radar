import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { API, LOCALE_ET } from '../constants';
import { getStoredLocale, setLocale, clearLocale, isAuthenticated } from '../lib/auth';
import { localizedTo } from '../utils';
import { useRouteLocale } from './useRouteLocale';

export interface UseLocaleMutationResult {
  locale: string;
  handleLocaleChange: (code: string) => void;
  isPending: boolean;
}

export interface UseLocaleMutationCallbacks {
  onSuccess?: () => void;
  onError?: (err: unknown) => void;
  // Home/Landing/Feed, Explore, EventDetail and Faq are the four public SEO
  // routes (see App.tsx's ROUTE_DEFS, issue #236 added Explore, #491 Faq): their bare
  // path must always render Estonian regardless of any stored preference,
  // so their initial locale resolves purely from the URL's `:locale`
  // segment. Every other page falls back to
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
    const prevLocale = locale;
    const prevStored = getStoredLocale();
    const prevTo = location.pathname + location.search;

    setLocaleState(code);
    // Persist before navigating, both branches: BareLocaleGate (App.tsx)
    // reads storage synchronously in the render the navigate below triggers,
    // so persisting after would leave a stale preference for that read and
    // bounce an Estonian switch (whose target is a bare path) right back.
    //
    // replace: true is intentional — a locale switch re-presents the same
    // page, so Back should return to the previous page (not the same page in
    // the old language), and it keeps a failed PATCH from leaving a dead
    // history entry in the new locale.
    if (!isAuthenticated()) {
      // Anonymous visitors (public EventDetail) have no session to persist
      // locale to — PATCH /users/me would 401 and trigger the client's
      // hard redirect to /login. Persist locally only in that case.
      setLocale(code);
      navigate(localizedTo(prevTo, code), { replace: true });
      callbacks?.onSuccess?.();
      return;
    }
    setLocale(code);
    navigate(localizedTo(prevTo, code), { replace: true });
    mutation.mutate(code, {
      onSuccess: () => {
        callbacks?.onSuccess?.();
      },
      onError: (err) => {
        if (prevStored === null) clearLocale();
        else setLocale(prevStored);
        setLocaleState(prevLocale);
        navigate(prevTo, { replace: true });
        callbacks?.onError?.(err);
      },
    });
  }

  return { locale, handleLocaleChange, isPending: mutation.isPending };
}
