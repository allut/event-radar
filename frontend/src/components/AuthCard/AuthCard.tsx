import type { ReactNode } from 'react';
import { t } from '../../i18n';
import { cx } from '../../utils';
import { BRAND_GLYPH, type AuthCardKind } from '../../constants';
import styles from './AuthCard.module.css';

export type { AuthCardKind };

interface AuthCardProps {
  locale: string;
  kind: AuthCardKind;
  message: string;
  /** Fades the status block in on mount — the verify routes want this, the
   * unsubscribe route's original design didn't, so it stays opt-out. */
  animated?: boolean;
  /** Extra content below the message — a retry link, a resubscribe button. */
  action?: ReactNode;
}

/** Shared page/card/radar/brand shell + status block (spinner/check/error)
 * for the auth-verify and unsubscribe routes. Presentational only — token
 * storage, redirects, and endpoint calls stay in each route's own component. */
export default function AuthCard({ locale, kind, message, animated = true, action }: AuthCardProps) {
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <span className={styles.radar} aria-hidden>{BRAND_GLYPH}</span>
        <h1 className={styles.brand}>{t('brand', locale)}</h1>

        <div
          className={cx(styles.status, animated && styles.statusAnimated)}
          role={kind === 'error' ? 'alert' : 'status'}
          aria-live={kind === 'pending' ? 'polite' : undefined}
        >
          {kind === 'pending' && <span className={styles.spinner} aria-label={message} />}
          {kind === 'success' && <div className={styles.check}>✓</div>}
          {kind === 'error' && <div className={styles.errorIcon}>✕</div>}
          <p className={styles.message}>{message}</p>
          {action}
        </div>
      </div>
    </div>
  );
}
