import { Link } from 'react-router-dom';
import { getLocale } from '../../lib/auth';
import { MAGIC_LINK_EXPIRY_MINUTES, UI_STATE } from '../../constants';
import { t, ti } from '../../i18n';
import { useMagicLinkRequest } from '../../hooks/useMagicLinkRequest';
import styles from './OrganizerLogin.module.css';

export default function OrganizerLogin() {
  const locale = getLocale();
  const { email, setEmail, state, errorMsg, submit, reset } =
    useMagicLinkRequest(locale, '/organizer/auth/request-link');

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <header className={styles.header}>
          <span className={styles.radar} aria-hidden>◉</span>
          <h1 className={styles.brand}>{t('brand', locale)}</h1>
        </header>

        <p className={styles.tagline}>{t('organizer_tagline', locale)}</p>

        {state === UI_STATE.success ? (
          <div className={styles.success} role="status">
            <div className={styles.checkCircle}>✓</div>
            <p className={styles.successMsg}>
              {t('check_inbox', locale)} <strong>{email}</strong>
            </p>
            <p className={styles.successHint}>
              {ti('link_expires', locale, { minutes: String(MAGIC_LINK_EXPIRY_MINUTES) })}
            </p>
            <button className={styles.resend} onClick={reset}>
              {t('use_different', locale)}
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className={styles.form} noValidate>
            <label className={styles.label} htmlFor="organizer-email">{t('email_label', locale)}</label>
            <input
              id="organizer-email"
              type="email"
              className={styles.input}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t('email_placeholder', locale)}
              autoFocus
              autoComplete="email"
              disabled={state === UI_STATE.loading}
              required
            />

            {state === UI_STATE.error && (
              <p className={styles.error} role="alert">{errorMsg}</p>
            )}

            <button
              type="submit"
              className={styles.submit}
              disabled={state === UI_STATE.loading || !email.trim()}
            >
              {state === UI_STATE.loading
                ? <span className={styles.spinner} aria-label={t('sending', locale)} />
                : t('send_link', locale)}
            </button>
          </form>
        )}

        <p className={styles.note}>{t('no_password', locale)}</p>
        <Link to="/" className={styles.backLink}>{t('organizer_back_to_site', locale)}</Link>
      </div>
    </div>
  );
}
