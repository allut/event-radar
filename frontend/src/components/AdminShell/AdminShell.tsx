import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import { BRAND_GLYPH } from '../../constants/core';
import { ADMIN_NAV_ITEMS, ROUTES } from '../../constants/routes';
import { useAdminLogout } from '../../hooks/useAdminLogout';
import AdminThemeToggle from '../AdminThemeToggle';
import styles from './AdminShell.module.css';

interface AdminShellProps {
  children: ReactNode;
}

// Minimal admin-console chrome — persistent nav rail + content pane, not the
// public app's TopBar/Footer (issue #154). Nav always lists all five
// clickable screens regardless of viewport (no mobile collapse — this is an
// operator tool, not the consumer/organizer product surface).
export default function AdminShell({ children }: AdminShellProps) {
  const logout = useAdminLogout();

  return (
    <div className={styles.shell}>
      <aside className={styles.rail}>
        <div className={styles.brandRow}>
          <span className={styles.radar} aria-hidden>{BRAND_GLYPH}</span>
          <span className={styles.name}>Radar</span>
          <span className={styles.badge}>Admin</span>
        </div>
        <nav className={styles.nav} aria-label="Admin">
          {ADMIN_NAV_ITEMS.map(({ route, label }) => (
            <NavLink
              key={route}
              to={route}
              end={route === ROUTES.adminDashboard}
              className={({ isActive }) => (isActive ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink)}
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className={styles.foot}>
          <AdminThemeToggle />
          <button type="button" className={styles.signOut} onClick={logout}>Sign out →</button>
        </div>
      </aside>
      <main className={styles.content}>{children}</main>
    </div>
  );
}
