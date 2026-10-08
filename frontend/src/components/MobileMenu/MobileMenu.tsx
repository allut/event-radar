import { Link, NavLink } from 'react-router-dom';
import { t } from '../../i18n';
import { cx } from '../../utils';
import { NAV_ITEMS, ROUTES, SIGNED_OUT_NAV_ITEMS, type NavItem } from '../../constants';
import { useDropdown } from '../../hooks/useDropdown';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useScrollLock } from '../../hooks/useScrollLock';
import { Identity, type AccountTrack } from '../AccountMenu';
import { SearchField } from '../BarSearch';
import { PrefsRows } from '../PrefsMenu';
import barStyles from '../shared/Bar.module.css';
import styles from './MobileMenu.module.css';

interface MobileMenuProps {
  locale: string;
  onLocaleChange: (code: string) => void;
  onLogout?: () => void;
  localeDisabled?: boolean;
  showNav?: boolean;
  authed?: boolean;
  // Overrides the default consumer nav — e.g. OrganizerTopBar passes
  // ORGANIZER_NAV_ITEMS.
  navItems?: readonly NavItem[];
  navAriaLabelKey?: string;
  // Settings / Contact: shown in the signed-in account block, not the nav.
  accountItems?: readonly NavItem[];
  track?: AccountTrack;
  showSearch?: boolean;
}

// The phone drawer: nav in large Cormorant, then search, language + theme, and
// (signed in) the account block. Signed out, the bar's own "Logi sisse" is the
// primary action, so it is not repeated here.
export default function MobileMenu({
  locale, onLocaleChange, onLogout, localeDisabled, showNav = true, authed = true,
  navItems, navAriaLabelKey = 'nav_daily5', accountItems = [], track = 'consumer', showSearch = false,
}: MobileMenuProps) {
  // Opening focuses the first nav item, never the search field: that would pop
  // the phone keyboard.
  const { open, setOpen, rootRef, popRef, triggerRef, close } = useDropdown('nav a, button[aria-pressed]');
  const localePath = useLocalePath();
  useScrollLock(open);
  const visibleNavItems = navItems ?? (authed ? NAV_ITEMS : SIGNED_OUT_NAV_ITEMS);

  return (
    <div className={styles.root} ref={rootRef} data-drawer-open={open || undefined}>
      <button
        ref={triggerRef}
        type="button"
        className={cx(barStyles.iconBtn, styles.trigger)}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={t('menu', locale)}
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden>{open ? '✕' : '☰'}</span>
      </button>
      {open && (
        <div className={styles.drawer} ref={popRef}>
          {showNav && visibleNavItems.length > 0 && (
            <nav className={styles.nav} aria-label={t(navAriaLabelKey, locale)}>
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
          )}

          {showSearch && <SearchField locale={locale} className={styles.search} onDone={close} />}

          <div className={styles.prefs}>
            <PrefsRows locale={locale} onLocaleChange={onLocaleChange} localeDisabled={localeDisabled} onPicked={close} />
          </div>

          {authed && (
            <div className={styles.account}>
              <Identity locale={locale} track={track} className={styles.identity} />
              {accountItems.map(({ route, labelKey }) => (
                <Link key={route} to={localePath(route)} className={styles.accountLink} onClick={close}>
                  {t(labelKey, locale)}
                </Link>
              ))}
              <button type="button" className={barStyles.btn} onClick={() => { close(); onLogout?.(); }}>
                {t('sign_out', locale)}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
