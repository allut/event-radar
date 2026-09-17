import { Link, NavLink } from 'react-router-dom';
import { t } from '../../i18n';
import { cx } from '../../utils';
import { BRAND_GLYPH, NAV_ITEMS, ROUTES, SIGNED_OUT_NAV_ITEMS } from '../../constants';
import { useLocalePath } from '../../hooks/useLocalePath';
import LocaleSelector from '../LocaleSelector';
import ThemeSelector from '../ThemeSelector';
import MobileMenu from '../MobileMenu';
import styles from './TopBar.module.css';

interface TopBarProps {
  locale: string;
  onLocaleChange: (code: string) => void;
  onLogout?: () => void;
  localeDisabled?: boolean;
  onBack?: () => void;
  authed?: boolean;
  showNav?: boolean;
}

export default function TopBar({ locale, onLocaleChange, onLogout, localeDisabled, onBack, authed = true, showNav = true }: TopBarProps) {
  const localePath = useLocalePath();
  // Signed-out chrome (issue #235): only the public routes in
  // SIGNED_OUT_NAV_ROUTES stay visible — the rest are dead ends for an
  // anonymous visitor.
  const visibleNavItems = authed ? NAV_ITEMS : SIGNED_OUT_NAV_ITEMS;
  return (
    <header className={styles.topBar}>
      <div className={styles.left}>
        <Link to={localePath(ROUTES.home)} className={styles.logoWrap}>
          <span className={styles.radar} aria-hidden>{BRAND_GLYPH}</span>
          <span className={styles.brand}>{t('brand', locale)}</span>
        </Link>
      </div>

      {showNav && visibleNavItems.length > 0 && (
        <nav className={styles.nav} aria-label={t('nav_daily5', locale)}>
          {visibleNavItems.map(({ route, labelKey }) => (
            <NavLink
              key={route}
              to={localePath(route)}
              end={route === ROUTES.home}
              className={({ isActive }) => cx(styles.navLink, isActive && styles.navLinkActive)}
            >
              {t(labelKey, locale)}
            </NavLink>
          ))}
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
          <Link to={localePath(ROUTES.login)} className={styles.authBtn}>{t('sign_in', locale)}</Link>
        )}
        <div className={styles.localeWrap}>
          <LocaleSelector
            locale={locale}
            onChange={onLocaleChange}
            ariaLabel={t('section_language', locale)}
            disabled={localeDisabled}
          />
        </div>
        <div className={styles.themeWrap}>
          <ThemeSelector locale={locale} ariaLabel={t('section_theme', locale)} />
        </div>
        <div className={styles.mobileMenuWrap}>
          <MobileMenu
            locale={locale}
            onLocaleChange={onLocaleChange}
            onLogout={onLogout}
            localeDisabled={localeDisabled}
            showNav={showNav}
            authed={authed}
          />
        </div>
      </div>
    </header>
  );
}
