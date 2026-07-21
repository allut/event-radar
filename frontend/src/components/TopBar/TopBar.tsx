import { Link, NavLink } from 'react-router-dom';
import { t } from '../../i18n';
import { cx } from '../../utils';
import LocaleSelector from '../LocaleSelector';
import MobileMenu from '../MobileMenu';
import styles from './TopBar.module.css';

interface TopBarProps {
  locale: string;
  onLocaleChange: (code: string) => void;
  onLogout?: () => void;
  localeDisabled?: boolean;
  onBack?: () => void;
  authed?: boolean;
}

export default function TopBar({ locale, onLocaleChange, onLogout, localeDisabled, onBack, authed = true }: TopBarProps) {
  return (
    <header className={cx(styles.topBar, !authed && styles.minimal)}>
      <div className={styles.left}>
        <Link to="/" className={styles.logoWrap}>
          <span className={styles.radar} aria-hidden>◉</span>
          <span className={styles.brand}>{t('brand', locale)}</span>
        </Link>
      </div>

      {authed && (
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
      )}

      <div className={styles.actions}>
        {onBack && (
          <button className={styles.backBtn} onClick={onBack} aria-label={t('back', locale)}>
            <span className={styles.backIcon} aria-hidden>←</span>
            {t('back', locale)}
          </button>
        )}
        {authed && onLogout && (
          <button className={styles.authBtn} onClick={onLogout}>{t('sign_out', locale)}</button>
        )}
        {!authed && (
          <Link to="/login" className={styles.authBtn}>{t('sign_in', locale)}</Link>
        )}
        <div className={styles.localeWrap}>
          <LocaleSelector
            locale={locale}
            onChange={onLocaleChange}
            ariaLabel={t('section_language', locale)}
            disabled={localeDisabled}
          />
        </div>
        {authed && (
          <div className={styles.mobileMenuWrap}>
            <MobileMenu
              locale={locale}
              onLocaleChange={onLocaleChange}
              onLogout={onLogout ?? (() => undefined)}
              localeDisabled={localeDisabled}
            />
          </div>
        )}
      </div>
    </header>
  );
}
