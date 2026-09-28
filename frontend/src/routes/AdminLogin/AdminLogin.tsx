import { BRAND_GLYPH, TOTP_CODE_LENGTH, UI_STATE } from '../../constants';
import { useAdminLogin } from '../../hooks/useAdminLogin';
import styles from './AdminLogin.module.css';

// Admin console entry point — password + TOTP, single-submit form (issue
// #154). No i18n, no locale prefix, no in-app link here — entry is
// typed-URL/bookmark only. The noindex meta is emitted once by AdminApp,
// which wraps every /admin/* route including this one (see AdminApp).
export default function AdminLogin() {
  const { username, setUsername, password, setPassword, totpCode, setTotpCode, state, errorMsg, submit } = useAdminLogin();
  const loading = state === UI_STATE.loading;

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <header className={styles.header}>
          <span className={styles.radar} aria-hidden>{BRAND_GLYPH}</span>
          <span className={styles.brand}>Event Radar</span>
        </header>
        <p className={styles.tag}>Admin Console</p>

        <form onSubmit={submit} className={styles.form} noValidate>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="admin-username">Username</label>
            <input
              id="admin-username"
              type="text"
              className={styles.input}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              disabled={loading}
              required
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor="admin-password">Password</label>
            <input
              id="admin-password"
              type="password"
              className={styles.input}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              disabled={loading}
              required
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor="admin-totp">TOTP code</label>
            <input
              id="admin-totp"
              type="text"
              inputMode="numeric"
              className={styles.input}
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value)}
              placeholder={'0'.repeat(TOTP_CODE_LENGTH)}
              maxLength={TOTP_CODE_LENGTH}
              autoComplete="one-time-code"
              disabled={loading}
              required
            />
          </div>

          {state === UI_STATE.error && (
            <p className={styles.error} role="alert">{errorMsg}</p>
          )}

          <button type="submit" className={styles.submit} disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className={styles.foot}>Session &middot; 12h TTL &middot; no recovery codes</p>
      </div>
    </div>
  );
}
