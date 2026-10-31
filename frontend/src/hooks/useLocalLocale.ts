import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { LOCALE_ET } from '../constants/core';
import { getStoredLocale, setLocale } from '../lib/auth';
import { isValidLocale } from '../utils/locale';
import { localizedTo } from '../lib/urlLocale';

/** URL-backed locale for the organizer portal and Onboarding — routes that
 * have no PATCH /users/me-style locale endpoint to mirror. The locale is
 * derived from the `:locale` URL segment (else the stored preference, else
 * Estonian — the same resolution as useLocaleMutation's non-public path), so
 * the shown language can never disagree with the URL. Switching persists the
 * choice and navigates to the equivalent path under the new prefix. */
export function useLocalLocale(): [string, (code: string) => void] {
  const { locale: urlLocale } = useParams<{ locale?: string }>();
  const { pathname, search, hash } = useLocation();
  const navigate = useNavigate();

  const locale = isValidLocale(urlLocale) ? urlLocale : (getStoredLocale() ?? LOCALE_ET);

  function handleLocaleChange(code: string): void {
    // Persist before navigating: BareLocaleGate (App.tsx) reads storage
    // synchronously in the render the navigate below triggers — see
    // useLocaleMutation. replace: true so Back skips locale variants.
    setLocale(code);
    navigate(localizedTo(pathname + search + hash, code), { replace: true });
  }

  return [locale, handleLocaleChange];
}
