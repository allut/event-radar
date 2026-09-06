import { type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { t, ti } from '../../i18n';
import { isOrganizerPortalPath, safeUrl } from '../../utils';
import { BRAND_GLYPH, ROUTES, SOCIAL_LINKS, type SocialIcon } from '../../constants';
import { useLocale } from '../../hooks/useLocale';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useOrganizerAuth } from '../../hooks/useOrganizerAuth';
import styles from './Footer.module.css';

// Self-contained brand glyphs — no external assets, so the footer works under
// the app's strict same-origin constraints. currentColor lets CSS drive hover.
const SOCIAL_ICONS: Record<SocialIcon, ReactNode> = {
  instagram: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden focusable="false">
      <rect x="2.5" y="2.5" width="19" height="19" rx="5" />
      <circle cx="12" cy="12" r="4.2" />
      <circle cx="17.4" cy="6.6" r="1.1" fill="currentColor" stroke="none" />
    </svg>
  ),
  facebook: (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden focusable="false">
      <path d="M14 8.5V6.8c0-.8.2-1.3 1.4-1.3H17V2.6C16.6 2.5 15.7 2.5 14.6 2.5c-2.3 0-3.9 1.4-3.9 4v2H8v3h2.7V21h3.3v-9.5h2.4l.4-3H14z" />
    </svg>
  ),
  twitter: (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden focusable="false">
      <path d="M17.5 3h3l-6.6 7.5L21.7 21h-6l-4.7-6.1L5.6 21H2.5l7-8-6.9-10h6.2l4.3 5.6L17.5 3zm-1 16h1.7L7.6 4.7H5.8L16.5 19z" />
    </svg>
  ),
};

export default function Footer() {
  const locale = useLocale();
  const localePath = useLocalePath();
  const isOrganizer = useOrganizerAuth();
  const { pathname } = useLocation();
  // On an organizer-portal page, an already-signed-in organizer gets the
  // authenticated organizer contact form instead of the public one — a
  // signed-out visitor there (e.g. /organizer/login) still gets the public
  // form, since /organizer/contact would just bounce them to login.
  const inOrganizerPortal = isOrganizerPortalPath(pathname) && isOrganizer;
  const contactRoute = inOrganizerPortal ? ROUTES.organizerContact : ROUTES.contact;
  const contactLabelKey = inOrganizerPortal ? 'organizer_contact_nav' : 'footer_contact';
  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>
        <div className={styles.brandRow}>
          <Link to={localePath(ROUTES.home)} className={styles.brandLink}>
            <span className={styles.radarMark} aria-hidden>{BRAND_GLYPH}</span>
            <span>{t('brand', locale)}</span>
          </Link>
          <span>{t('footer_location', locale)}</span>
        </div>

        <nav className={styles.links} aria-label={t('footer_nav', locale)}>
          <Link to={localePath(ROUTES.privacy)} className={styles.link}>{t('footer_privacy', locale)}</Link>
          <Link to={localePath(ROUTES.terms)} className={styles.link}>{t('footer_terms', locale)}</Link>
          <Link to={localePath(contactRoute)} className={styles.link}>{t(contactLabelKey, locale)}</Link>
          <Link to={localePath(isOrganizer ? ROUTES.organizerDashboard : ROUTES.organizerLogin)} className={styles.link}>
            {t(isOrganizer ? 'footer_organizer_dashboard' : 'footer_organizers', locale)}
          </Link>
        </nav>

        <div className={styles.social} aria-label={t('footer_social', locale)}>
          {SOCIAL_LINKS.map((s) => {
            const href = safeUrl(s.url);
            if (!href) return null;
            return (
              <a
                key={s.icon}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.socialLink}
                aria-label={t(`social_${s.icon}`, locale)}
              >
                {SOCIAL_ICONS[s.icon]}
              </a>
            );
          })}
        </div>

        <p className={styles.copyright}>
          {ti('footer_copyright', locale, { year: String(new Date().getFullYear()) })}
        </p>
      </div>
    </footer>
  );
}
