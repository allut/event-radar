import { NavLink } from 'react-router-dom';
import { ROUTES, type NavItem } from '../../constants/routes';
import { t } from '../../i18n';
import { cx } from '../../utils';
import { useLocalePath } from '../../hooks/useLocalePath';
import styles from '../shared/Bar.module.css';

interface BarNavProps {
  items: readonly NavItem[];
  locale: string;
  ariaLabel: string;
}

export default function BarNav({ items, locale, ariaLabel }: BarNavProps) {
  const localePath = useLocalePath();
  return (
    <nav className={styles.nav} aria-label={ariaLabel}>
      {items.map(({ route, labelKey }) => (
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
  );
}
