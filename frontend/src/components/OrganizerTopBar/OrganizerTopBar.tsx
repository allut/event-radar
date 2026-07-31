import { Link, NavLink } from 'react-router-dom';
import { t } from '../../i18n';
import { cx } from '../../utils';
import LocaleSelector from '../LocaleSelector';
import styles from './OrganizerTopBar.module.css';

interface OrganizerTopBarProps {
  locale: string;
  onLocaleChange: (code: string) => void;
  onLogout: () => void;
}

// Organizer-scoped sibling of components/TopBar — deliberately not reused
// directly, since that component's nav/auth links are hardcoded to the
// consumer track (/login, /explore, /saved, ...). Kept minimal: two nav
// links instead of TopBar's four, no mobile hamburger menu.
export default function OrganizerTopBar({ locale, onLocaleChange, onLogout }: OrganizerTopBarProps) {
  return (
    <header className={styles.topBar}>
      <div className={styles.left}>
        <Link to="/" className={styles.logoWrap}>
          <span className={styles.radar} aria-hidden>◉</span>
          <span className={styles.brand}>{t('brand', locale)}</span>
        </Link>
      </div>

      <nav className={styles.nav} aria-label={t('organizer_dashboard_title', locale)}>
        <NavLink
          to="/organizer/dashboard"
          className={({ isActive }) => cx(styles.navLink, isActive && styles.navLinkActive)}
        >
          {t('organizer_dashboard_title', locale)}
        </NavLink>
        <NavLink
          to="/organizer/submit"
          className={({ isActive }) => cx(styles.navLink, isActive && styles.navLinkActive)}
        >
          {t('organizer_new_event', locale)}
        </NavLink>
      </nav>

      <div className={styles.actions}>
        <button className={styles.authBtn} onClick={onLogout}>{t('sign_out', locale)}</button>
        <LocaleSelector
          locale={locale}
          onChange={onLocaleChange}
          ariaLabel={t('section_language', locale)}
        />
      </div>
    </header>
  );
}
