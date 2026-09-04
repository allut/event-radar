import { Link, NavLink } from 'react-router-dom';
import { t } from '../../i18n';
import { cx } from '../../utils';
import { LOCALES, NAV_ITEMS, ROUTES, THEME_OPTIONS } from '../../constants';
import { useDropdown } from '../../hooks/useDropdown';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useThemePreference } from '../../hooks/useThemePreference';
import { setThemePreference } from '../../lib/theme';
import menuStyles from '../shared/Menu.module.css';
import styles from './MobileMenu.module.css';

interface MobileMenuProps {
  locale: string;
  onLocaleChange: (code: string) => void;
  onLogout?: () => void;
  localeDisabled?: boolean;
  showNav?: boolean;
  authed?: boolean;
}

export default function MobileMenu({ locale, onLocaleChange, onLogout, localeDisabled, showNav = true, authed = true }: MobileMenuProps) {
  const { open, setOpen, flip, rootRef, popRef, triggerRef, close } = useDropdown();
  const localePath = useLocalePath();
  const themePreference = useThemePreference();
  // Mirrors TopBar's signed-out nav filtering — Explore stays visible, the
  // rest are dead ends for an anonymous visitor.
  const visibleNavItems = authed ? NAV_ITEMS : NAV_ITEMS.filter((item) => item.route === ROUTES.explore);

  return (
    <div className={cx(menuStyles.menu, styles.mobileMenu)} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={t('menu', locale)}
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden>☰</span>
      </button>
      {open && (
        <div className={styles.pop} ref={popRef} data-flip={flip || undefined}>
          {showNav && visibleNavItems.length > 0 && (
            <>
              <nav className={styles.section} aria-label={t('nav_daily5', locale)}>
                {visibleNavItems.map(({ route, labelKey }) => (
                  <NavLink
                    key={route}
                    to={localePath(route)}
                    end={route === ROUTES.home}
                    className={({ isActive }) => cx(styles.link, isActive && styles.linkActive)}
                    onClick={close}
                  >
                    {t(labelKey, locale)}
                  </NavLink>
                ))}
              </nav>

              <div className={styles.divider} />
            </>
          )}

          <div className={styles.section}>
            <span className={styles.sectionLabel}>{t('section_language', locale)}</span>
            <div className={styles.optionRow} role="group" aria-label={t('section_language', locale)}>
              {LOCALES.map(({ code, label }) => {
                const isActive = code === locale;
                return (
                  <button
                    key={code}
                    type="button"
                    className={cx(styles.option, isActive && styles.optionActive)}
                    aria-pressed={isActive}
                    disabled={localeDisabled}
                    onClick={() => {
                      onLocaleChange(code);
                      close();
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className={styles.divider} />

          <div className={styles.section}>
            <span className={styles.sectionLabel}>{t('section_theme', locale)}</span>
            <div className={styles.optionRow} role="group" aria-label={t('section_theme', locale)}>
              {THEME_OPTIONS.map(({ value, labelKey }) => {
                const isActive = value === themePreference;
                return (
                  <button
                    key={value}
                    type="button"
                    className={cx(styles.option, isActive && styles.optionActive)}
                    aria-pressed={isActive}
                    onClick={() => {
                      setThemePreference(value);
                      close();
                    }}
                  >
                    {t(labelKey, locale)}
                  </button>
                );
              })}
            </div>
          </div>

          <div className={styles.divider} />

          <div className={styles.section}>
            {authed ? (
              <button
                type="button"
                className={styles.signOut}
                onClick={() => {
                  onLogout?.();
                  close();
                }}
              >
                {t('sign_out', locale)}
              </button>
            ) : (
              <Link to={localePath(ROUTES.login)} className={styles.signOut} onClick={close}>
                {t('sign_in', locale)}
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
