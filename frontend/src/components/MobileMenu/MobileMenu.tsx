import { Link, NavLink } from 'react-router-dom';
import { t } from '../../i18n';
import { cx } from '../../utils';
import { LOCALES, ROUTES } from '../../constants';
import { useDropdown } from '../../hooks/useDropdown';
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
          {authed && showNav && (
            <>
              <nav className={styles.section} aria-label={t('nav_daily5', locale)}>
                <NavLink
                  to={ROUTES.home}
                  end
                  className={({ isActive }) => cx(styles.link, isActive && styles.linkActive)}
                  onClick={close}
                >
                  {t('nav_daily5', locale)}
                </NavLink>
                <NavLink
                  to={ROUTES.explore}
                  className={({ isActive }) => cx(styles.link, isActive && styles.linkActive)}
                  onClick={close}
                >
                  {t('nav_explore', locale)}
                </NavLink>
                <NavLink
                  to={ROUTES.saved}
                  className={({ isActive }) => cx(styles.link, isActive && styles.linkActive)}
                  onClick={close}
                >
                  {t('nav_saved', locale)}
                </NavLink>
                <NavLink
                  to={ROUTES.settings}
                  className={({ isActive }) => cx(styles.link, isActive && styles.linkActive)}
                  onClick={close}
                >
                  {t('nav_settings', locale)}
                </NavLink>
              </nav>

              <div className={styles.divider} />
            </>
          )}

          <div className={styles.section}>
            <span className={styles.sectionLabel}>{t('section_language', locale)}</span>
            <div className={styles.localeRow} role="group" aria-label={t('section_language', locale)}>
              {LOCALES.map(({ code, label }) => {
                const isActive = code === locale;
                return (
                  <button
                    key={code}
                    type="button"
                    className={cx(styles.localeOption, isActive && styles.localeOptionActive)}
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
              <Link to={ROUTES.login} className={styles.signOut} onClick={close}>
                {t('sign_in', locale)}
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
