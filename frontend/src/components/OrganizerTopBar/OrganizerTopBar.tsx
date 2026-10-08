import { Link } from 'react-router-dom';
import { t } from '../../i18n';
import { ORGANIZER_ACCOUNT_MENU_ITEMS, ORGANIZER_NAV_ITEMS, ROUTES } from '../../constants';
import { useBarScrolled } from '../../hooks/useBarScrolled';
import { useLocalePath } from '../../hooks/useLocalePath';
import AccountMenu from '../AccountMenu';
import BarLogo from '../BarLogo';
import BarNav from '../BarNav';
import MobileMenu from '../MobileMenu';
import PrefsMenu from '../PrefsMenu';
import styles from '../shared/Bar.module.css';

interface OrganizerTopBarProps {
  locale: string;
  onLocaleChange: (code: string) => void;
  onLogout: () => void;
}

// Organizer-scoped sibling of components/TopBar — deliberately not merged with
// it, since that component's nav/auth links are hardcoded to the consumer track
// (/login, /explore, /saved, ...). No search and no pulse chip; "New event" is
// the gold call-to-action, and Settings/Contact live in the account menu.
export default function OrganizerTopBar({ locale, onLocaleChange, onLogout }: OrganizerTopBarProps) {
  const localePath = useLocalePath();
  const scrolled = useBarScrolled();
  const newEvent = (
    <Link to={localePath(ROUTES.organizerSubmit)} className={styles.cta}>{t('organizer_new_event', locale)}</Link>
  );

  return (
    <header className={styles.bar} data-condensed={scrolled || undefined}>
      <div className={styles.barLeft}>
        {/* RU at 390px: wordmark + "Новое событие" + ☰ don't fit, so phones show the mark only. */}
        <BarLogo locale={locale} markOnlyOnPhone />
      </div>

      <BarNav items={ORGANIZER_NAV_ITEMS} locale={locale} ariaLabel={t('organizer_dashboard_title', locale)} />

      <div className={styles.actions}>
        <span className={styles.deskOnly}>{newEvent}</span>
        <span className={styles.deskOnly}>
          <AccountMenu locale={locale} track="organizer" items={ORGANIZER_ACCOUNT_MENU_ITEMS} onLogout={onLogout} />
        </span>
        <span className={styles.deskOnly}>
          <PrefsMenu locale={locale} onLocaleChange={onLocaleChange} />
        </span>

        <span className={styles.phoneOnly}>{newEvent}</span>
        <span className={styles.phoneOnly}>
          <MobileMenu
            locale={locale}
            onLocaleChange={onLocaleChange}
            onLogout={onLogout}
            navItems={ORGANIZER_NAV_ITEMS}
            accountItems={ORGANIZER_ACCOUNT_MENU_ITEMS}
            navAriaLabelKey="organizer_dashboard_title"
            track="organizer"
          />
        </span>
      </div>
    </header>
  );
}
