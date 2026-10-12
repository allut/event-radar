import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, organizerApi } from '../../api/client';
import { API, QUERY_KEYS } from '../../constants/api';
import type { NavItem } from '../../constants/routes';
import { t } from '../../i18n';
import { cx } from '../../utils';
import { useDropdown } from '../../hooks/useDropdown';
import { useLocalePath } from '../../hooks/useLocalePath';
import styles from '../shared/Bar.module.css';

export type AccountTrack = 'consumer' | 'organizer';

interface AccountIdentity {
  email: string;
  name?: string | null;
}

interface IdentityProps {
  locale: string;
  track: AccountTrack;
  className?: string;
}

// Fetched when the menu (or drawer) opens, never on mount: /auth/me and
// /organizer/profile are 10/min per IP, and a 401 from either hard-redirects to
// login, so this must not run speculatively on a public route.
export function Identity({ locale, track, className }: IdentityProps) {
  const { data } = useQuery({
    queryKey: track === 'consumer' ? [QUERY_KEYS.authMe] : [QUERY_KEYS.organizerProfile],
    queryFn: () => (track === 'consumer'
      ? api.get<AccountIdentity>(API.authMe)
      : organizerApi.get<AccountIdentity>(API.organizerProfile)),
    staleTime: Infinity,
    retry: false,
  });
  return (
    <div className={cx(styles.popId, className)} role="presentation">
      {t('account_signed_in_as', locale)}
      <b>{data ? (data.name ?? data.email) : ' '}</b>
      {data?.name && <span>{data.email}</span>}
    </div>
  );
}

interface AccountMenuProps {
  locale: string;
  track: AccountTrack;
  items: readonly NavItem[];
  onLogout: () => void;
}

// The trigger depends only on signed-in/out (no name or email, no avatar —
// ADR 0002) so it can't add a second layout shift on hydrate.
export default function AccountMenu({ locale, track, items, onLogout }: AccountMenuProps) {
  const { open, setOpen, rootRef, popRef, triggerRef, close } = useDropdown('a, button');
  const localePath = useLocalePath();
  return (
    <div className={styles.anchor} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={styles.trigger}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {t('account_menu', locale)}
        <svg className={styles.chev} viewBox="0 0 8 8" aria-hidden="true">
          <path d="M1 2.5 4 5.5 7 2.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
        </svg>
      </button>
      {open && (
        <div className={styles.pop} ref={popRef} role="menu">
          <Identity locale={locale} track={track} />
          {items.map(({ route, labelKey }) => (
            <Link key={route} to={localePath(route)} role="menuitem" className={styles.popItem} onClick={close}>
              {t(labelKey, locale)}
            </Link>
          ))}
          <hr className={styles.popRule} />
          <button
            type="button"
            role="menuitem"
            className={styles.popItem}
            onClick={() => {
              close();
              onLogout();
            }}
          >
            {t('sign_out', locale)}
          </button>
        </div>
      )}
    </div>
  );
}
