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
import { useOrganizerAuth } from '../../hooks/useOrganizerAuth';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import MagicLinkForm from '../../components/MagicLinkForm';
import GoogleSignInButton from '../../components/shared/GoogleSignInButton';
import SeoTags from '../../components/SeoTags';
import styles from './Login.module.css';

export default function Login() {
  const googleSignInEnabled = import.meta.env.VITE_GOOGLE_SIGNIN_CONSUMER_ENABLED === 'true';
  const locale = getLocale();
  const isOrganizer = useOrganizerAuth();
  const localePath = useLocalePath();
  const seoMeta = useStaticSeoMeta('seo_title_login', locale);
  const [termsBefore, termsAfter = ''] = t('login_terms_notice', locale).split('{terms}');
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

        <p className={styles.tagline}>{t('tagline', locale)}</p>

        {errorMessage && <p className={styles.error} role="alert">{errorMessage}</p>}

        {googleSignInEnabled && (
          <GoogleSignInButton href={`${API_BASE}${API.authGoogleStart}`} locale={locale} />
        )}

        {googleSignInEnabled && !emailExpanded && (
          <button type="button" className={styles.emailToggle} onClick={() => setEmailExpanded(true)}>
            {t('auth.googleSignIn.continueWithEmail', locale)}
          </button>
        )}

        {emailExpanded && (
          <>
            {googleSignInEnabled && <div className={styles.divider}>{t('auth.googleSignIn.orDivider', locale)}</div>}
            <MagicLinkForm locale={locale} emailFieldId="email" successAnimated />
          </>
        )}

        <p className={styles.note}>{t('no_password', locale)}</p>
        <p className={styles.terms}>
          {termsBefore}
          <Link to={localePath(ROUTES.terms)} className={styles.termsLink}>{t('login_terms_link', locale)}</Link>
          {termsAfter}
        </p>
        <p className={styles.terms}>
          <Link to={localePath(isOrganizer ? ROUTES.organizerDashboard : ROUTES.organizerLogin)} className={styles.termsLink}>
            {t('organizer_entry_link', locale)}
          </Link>
        </p>
      </div>
    </div>
  );
}
