import { Link } from 'react-router-dom';
import { t } from '../../i18n';
import { cx } from '../../utils';
import {
  ACCOUNT_MENU_ITEMS,
  NAV_ITEMS,
  ROUTES,
  SIGNED_OUT_NAV_ITEMS,
} from '../../constants/routes';
import { useBarScrolled } from '../../hooks/useBarScrolled';
import { useLocalePath } from '../../hooks/useLocalePath';
import AccountMenu from '../AccountMenu';
import BarLogo from '../BarLogo';
import BarNav from '../BarNav';
import { SearchField, SearchPopover } from '../BarSearch';
import MobileMenu from '../MobileMenu';
import PrefsMenu from '../PrefsMenu';
import PulseChip from '../PulseChip';
import styles from '../shared/Bar.module.css';

interface TopBarProps {
  locale: string;
  onLocaleChange: (code: string) => void;
  onLogout?: () => void;
  localeDisabled?: boolean;
  onBack?: () => void;
  authed?: boolean;
  showNav?: boolean;
  /** Landing: no fill and no hairline until the page scrolls. */
  transparent?: boolean;
  /** Landing keeps its own hero counts, so it hides the pulse chip. */
  showPulse?: boolean;
  /** /explore has its own search field. */
  showSearch?: boolean;
}

export default function TopBar({
  locale, onLocaleChange, onLogout, localeDisabled, onBack, authed = true, showNav = true,
  transparent, showPulse = true, showSearch = true,
}: TopBarProps) {
  const localePath = useLocalePath();
  const scrolled = useBarScrolled();
  // Signed-out chrome (issue #235): the explicit SIGNED_OUT_NAV_ITEMS list of
  // public routes — the signed-in rest are dead ends for an anonymous visitor.
  const navItems = authed ? NAV_ITEMS : SIGNED_OUT_NAV_ITEMS;
  const signedIn = authed && !!onLogout;

  return (
    <header
      className={styles.bar}
      data-condensed={scrolled || undefined}
      data-transparent={(transparent && !scrolled) || undefined}
    >
      <div className={styles.barLeft}>
        <BarLogo locale={locale} />
        {showPulse && <span className={styles.wideOnly}><PulseChip locale={locale} /></span>}
      </div>

      {showNav && <BarNav items={navItems} locale={locale} ariaLabel={t('nav_daily5', locale)} />}

      <div className={styles.actions}>
        {onBack && (
          <button type="button" className={cx(styles.btn, styles.deskOnly)} onClick={onBack}>
            <span aria-hidden>←</span>
            {t('back', locale)}
          </button>
        )}
        {showSearch && <SearchField locale={locale} className={cx(styles.searchField, styles.wideOnly)} />}
        {showSearch && <SearchPopover locale={locale} className={styles.narrowOnly} />}
        {signedIn ? (
          <span className={styles.deskOnly}>
            <AccountMenu locale={locale} track="consumer" items={ACCOUNT_MENU_ITEMS} onLogout={onLogout} />
          </span>
        ) : (
          <Link to={localePath(ROUTES.login)} className={cx(styles.btn, styles.deskOnly)}>{t('sign_in', locale)}</Link>
        )}
        <span className={styles.deskOnly}>
          <PrefsMenu locale={locale} onLocaleChange={onLocaleChange} localeDisabled={localeDisabled} />
        </span>

        {/* Phone: one primary action, then the drawer. */}
        {signedIn
          ? showSearch && <SearchPopover locale={locale} className={styles.phoneOnly} />
          : <Link to={localePath(ROUTES.login)} className={cx(styles.btn, styles.phoneOnly)}>{t('sign_in', locale)}</Link>}
        <span className={styles.phoneOnly}>
          <MobileMenu
            locale={locale}
            onLocaleChange={onLocaleChange}
            onLogout={onLogout}
            localeDisabled={localeDisabled}
            showNav={showNav}
            authed={authed}
            navItems={navItems}
            accountItems={ACCOUNT_MENU_ITEMS}
            showSearch={showSearch}
          />
        </span>
      </div>
    </header>
  );
}
