import { useState } from 'react';
import { Link } from 'react-router-dom';
import { API, API_BASE } from '../../constants/api';
import { isGoogleSignInConsumerEnabled } from '../../constants/auth';
import { ROUTES } from '../../constants/routes';
import { t } from '../../i18n';
import { useGoogleSignInError } from '../../hooks/useGoogleSignInError';
import { useLocalePath } from '../../hooks/useLocalePath';
import { usePathLocale } from '../../hooks/usePathLocale';
import { useOrganizerAuth } from '../../hooks/useOrganizerAuth';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import DialMark from '../../components/DialMark';
import MagicLinkForm from '../../components/MagicLinkForm';
import GoogleSignInButton from '../../components/shared/GoogleSignInButton';
import SeoTags from '../../components/SeoTags';
import styles from './Login.module.css';

export default function Login() {
  const googleSignInEnabled = isGoogleSignInConsumerEnabled();
  const locale = usePathLocale();
  const isOrganizer = useOrganizerAuth();
  const localePath = useLocalePath();
  const seoMeta = useStaticSeoMeta('seo_title_login', locale);
  const [termsBefore, termsAfter = ''] = t('login_terms_notice', locale).split('{terms}');
  const [emailExpanded, setEmailExpanded] = useState(!googleSignInEnabled);
  const errorMessage = useGoogleSignInError(locale);

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <div className={styles.card}>
        <header className={styles.header}>
          <span className={styles.radar}><DialMark /></span>
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
