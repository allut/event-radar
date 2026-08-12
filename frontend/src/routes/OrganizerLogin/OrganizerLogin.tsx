import { Link } from 'react-router-dom';
import { getLocale } from '../../lib/auth';
import { API, BRAND_GLYPH, ROUTES } from '../../constants';
import { t } from '../../i18n';
import MagicLinkForm from '../../components/MagicLinkForm';
import styles from './OrganizerLogin.module.css';

export default function OrganizerLogin() {
  const locale = getLocale();

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <header className={styles.header}>
          <span className={styles.radar} aria-hidden>{BRAND_GLYPH}</span>
          <h1 className={styles.brand}>{t('brand', locale)}</h1>
        </header>

        <p className={styles.tagline}>{t('organizer_tagline', locale)}</p>

        <MagicLinkForm
          locale={locale}
          requestPath={API.organizerAuthRequestLink}
          organizer
          emailFieldId="organizer-email"
        />

        <p className={styles.note}>{t('no_password', locale)}</p>
        <Link to={ROUTES.home} className={styles.backLink}>{t('organizer_back_to_site', locale)}</Link>
      </div>
    </div>
  );
}
