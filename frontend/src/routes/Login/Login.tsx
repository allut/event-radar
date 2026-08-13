import { Link } from 'react-router-dom';
import { getLocale } from '../../lib/auth';
import { BRAND_GLYPH, ROUTES } from '../../constants';
import { t } from '../../i18n';
import { useOrganizerAuth } from '../../hooks/useOrganizerAuth';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import MagicLinkForm from '../../components/MagicLinkForm';
import SeoTags from '../../components/SeoTags';
import styles from './Login.module.css';

export default function Login() {
  const locale = getLocale();
  const isOrganizer = useOrganizerAuth();
  const seoMeta = useStaticSeoMeta('seo_title_login', locale);
  const [termsBefore, termsAfter = ''] = t('login_terms_notice', locale).split('{terms}');

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <div className={styles.card}>
        <header className={styles.header}>
          <span className={styles.radar} aria-hidden>{BRAND_GLYPH}</span>
          <h1 className={styles.brand}>{t('brand', locale)}</h1>
        </header>

        <p className={styles.tagline}>{t('tagline', locale)}</p>

        <MagicLinkForm locale={locale} emailFieldId="email" successAnimated />

        <p className={styles.note}>{t('no_password', locale)}</p>
        <p className={styles.terms}>
          {termsBefore}
          <Link to={ROUTES.terms} className={styles.termsLink}>{t('login_terms_link', locale)}</Link>
          {termsAfter}
        </p>
        <p className={styles.terms}>
          <Link to={isOrganizer ? ROUTES.organizerDashboard : ROUTES.organizerLogin} className={styles.termsLink}>
            {t('organizer_entry_link', locale)}
          </Link>
        </p>
      </div>
    </div>
  );
}
