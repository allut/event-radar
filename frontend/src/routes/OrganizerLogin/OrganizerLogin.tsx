import { useState } from 'react';
import { Link } from 'react-router-dom';
import { getLocale } from '../../lib/auth';
import {
  API,
  API_BASE,
  BRAND_GLYPH,
  isGoogleSignInOrganizerEnabled,
  ROUTES,
} from '../../constants';
import { t } from '../../i18n';
import { useGoogleSignInError } from '../../hooks/useGoogleSignInError';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import MagicLinkForm from '../../components/MagicLinkForm';
import GoogleSignInButton from '../../components/shared/GoogleSignInButton';
import SeoTags from '../../components/SeoTags';
import styles from './OrganizerLogin.module.css';

export default function OrganizerLogin() {
  const googleSignInEnabled = isGoogleSignInOrganizerEnabled();
  const locale = getLocale();
  const localePath = useLocalePath();
  const seoMeta = useStaticSeoMeta('seo_title_organizer_login', locale);
  const [emailExpanded, setEmailExpanded] = useState(!googleSignInEnabled);
  const errorMessage = useGoogleSignInError(locale);

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
