import { Link, NavLink } from 'react-router-dom';
import { t } from '../../i18n';
import { cx } from '../../utils';
import LocaleSelector from '../LocaleSelector';
import MobileMenu from '../MobileMenu';
import styles from './TopBar.module.css';

interface TopBarProps {
  locale: string;
  onLocaleChange: (code: string) => void;
  onLogout: () => void;
  localeDisabled?: boolean;
}

export default function TopBar({ locale, onLocaleChange, onLogout, localeDisabled }: TopBarProps) {
  return (
    <header className={styles.topBar}>
      <Link to="/" className={styles.logoWrap}>
        <span className={styles.radar} aria-hidden>◉</span>
        <span className={styles.brand}>{t('brand', locale)}</span>
      </Link>

      <nav className={styles.nav} aria-label={t('nav_daily5', locale)}>
        <NavLink
          to="/"
          end
          className={({ isActive }) => cx(styles.navLink, isActive && styles.navLinkActive)}
        >
          {t('nav_daily5', locale)}
        </NavLink>
        <NavLink
          to="/explore"
          className={({ isActive }) => cx(styles.navLink, isActive && styles.navLinkActive)}
        >
          {t('nav_explore', locale)}
        </NavLink>
        <NavLink
          to="/saved"
          className={({ isActive }) => cx(styles.navLink, isActive && styles.navLinkActive)}
        >
          {t('nav_saved', locale)}
        </NavLink>
        <NavLink
          to="/settings"
          className={({ isActive }) => cx(styles.navLink, isActive && styles.navLinkActive)}
        >
          {t('nav_settings', locale)}
        </NavLink>
      </nav>

      <div className={styles.topActions}>
        <button className={styles.logoutBtn} onClick={onLogout}>{t('sign_out', locale)}</button>
        <LocaleSelector
          locale={locale}
          onChange={onLocaleChange}
          ariaLabel={t('section_language', locale)}
          disabled={localeDisabled}
        />
      </div>

      <div className={styles.mobileMenuWrap}>
        <MobileMenu
          locale={locale}
          onLocaleChange={onLocaleChange}
          onLogout={onLogout}
          localeDisabled={localeDisabled}
        />
      </div>
    </header>
  );
}
