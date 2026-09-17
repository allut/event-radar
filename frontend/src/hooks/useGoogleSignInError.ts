import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { GOOGLE_SIGNIN_ERROR_DENIED, GOOGLE_SIGNIN_ERROR_PARAM } from '../constants';
import { t } from '../i18n';

/** Login/OrganizerLogin's shared Google-callback error banner: reads
 * GOOGLE_SIGNIN_ERROR_PARAM once at mount (not re-read from searchParams on
 * every render — the effect below strips the param from the URL right
 * after, so a later refresh/revisit on the same history entry doesn't
 * resurface a stale failure banner for a sign-in that already succeeded or
 * was abandoned), then strips it from the URL. Returns the localized error
 * copy to render, or null when there's nothing to show. */
export function useGoogleSignInError(locale: string): string | null {
  const [searchParams, setSearchParams] = useSearchParams();
  const [googleError] = useState(() => searchParams.get(GOOGLE_SIGNIN_ERROR_PARAM));

  useEffect(() => {
    if (!googleError) return;
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete(GOOGLE_SIGNIN_ERROR_PARAM);
      return next;
    }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return googleError
    ? t(
      googleError === GOOGLE_SIGNIN_ERROR_DENIED
        ? 'auth.googleSignIn.errorCancelled'
        : 'auth.googleSignIn.errorFailed',
      locale,
    )
    : null;
}
