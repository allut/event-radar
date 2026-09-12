import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { getLocale } from '../../lib/auth';
import {
  API,
  API_BASE,
  BRAND_GLYPH,
  GOOGLE_SIGNIN_ERROR_DENIED,
  GOOGLE_SIGNIN_ERROR_PARAM,
  ROUTES,
} from '../../constants';
import { t } from '../../i18n';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import MagicLinkForm from '../../components/MagicLinkForm';
import GoogleSignInButton from '../../components/shared/GoogleSignInButton';
import SeoTags from '../../components/SeoTags';
import styles from './OrganizerLogin.module.css';

export default function OrganizerLogin() {
  const googleSignInEnabled = import.meta.env.VITE_GOOGLE_SIGNIN_ORGANIZER_ENABLED === 'true';
  const locale = getLocale();
  const localePath = useLocalePath();
  const seoMeta = useStaticSeoMeta('seo_title_organizer_login', locale);
  const [searchParams, setSearchParams] = useSearchParams();
  const [emailExpanded, setEmailExpanded] = useState(!googleSignInEnabled);
  // Frozen at mount, not re-read from searchParams on every render — the
  // effect below strips the param from the URL right after, so a later
  // refresh/revisit on the same history entry doesn't resurface a stale
  // failure banner for a sign-in that already succeeded or was abandoned.
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

  const errorMessage = googleError
    ? t(
      googleError === GOOGLE_SIGNIN_ERROR_DENIED
        ? 'auth.googleSignIn.errorCancelled'
        : 'auth.googleSignIn.errorFailed',
      locale,
    )
    : null;

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <div className={styles.card}>
        <header className={styles.header}>
          <span className={styles.radar} aria-hidden>{BRAND_GLYPH}</span>
          <h1 className={styles.brand}>{t('brand', locale)}</h1>
        </header>

        <p className={styles.tagline}>{t('organizer_tagline', locale)}</p>

        {errorMessage && <p className={styles.error} role="alert">{errorMessage}</p>}

        {googleSignInEnabled && (
          <GoogleSignInButton href={`${API_BASE}${API.organizerAuthGoogleStart}`} locale={locale} />
        )}

        {googleSignInEnabled && !emailExpanded && (
          <button type="button" className={styles.emailToggle} onClick={() => setEmailExpanded(true)}>
            {t('auth.googleSignIn.continueWithEmail', locale)}
          </button>
        )}

        {emailExpanded && (
          <>
            {googleSignInEnabled && <div className={styles.divider}>{t('auth.googleSignIn.orDivider', locale)}</div>}
            <MagicLinkForm
              locale={locale}
              requestPath={API.organizerAuthRequestLink}
              organizer
              emailFieldId="organizer-email"
            />
          </>
        )}

        <p className={styles.note}>{t('no_password', locale)}</p>
        <Link to={localePath(ROUTES.home)} className={styles.backLink}>{t('organizer_back_to_site', locale)}</Link>
      </div>
    </div>
  );
}
