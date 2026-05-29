import { useState } from 'react';
import { api, ApiError } from '../../api/client';
import { getLocale } from '../../lib/auth';
import { MAGIC_LINK_EXPIRY_MINUTES, type LoginState } from '../../constants';
import { t, ti } from '../../i18n';
import styles from './Login.module.css';

export default function Login() {
  const locale = getLocale();
  const [email, setEmail] = useState('');
  const [state, setState] = useState<LoginState>('idle');
  const [errorMsg, setErrorMsg] = useState('');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) return;
    setState('loading');
    setErrorMsg('');
    try {
      await api.post('/auth/request-link', { email: trimmed.toLowerCase() });
      setState('success');
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : t('generic_error', locale));
      setState('error');
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <header className={styles.header}>
          <span className={styles.radar} aria-hidden>◉</span>
          <h1 className={styles.brand}>{t('brand', locale)}</h1>
        </header>

        <p className={styles.tagline}>{t('tagline', locale)}</p>

        {state === 'success' ? (
          <div className={styles.success} role="status">
            <div className={styles.checkCircle}>✓</div>
            <p className={styles.successMsg}>
              {t('check_inbox', locale)} <strong>{email}</strong>
            </p>
            <p className={styles.successHint}>
              {ti('link_expires', locale, { minutes: String(MAGIC_LINK_EXPIRY_MINUTES) })}
            </p>
            <button
              className={styles.resend}
              onClick={() => { setState('idle'); setEmail(''); }}
            >
              {t('use_different', locale)}
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className={styles.form} noValidate>
            <label className={styles.label} htmlFor="email">{t('email_label', locale)}</label>
            <input
              id="email"
              type="email"
              className={styles.input}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t('email_placeholder', locale)}
              autoFocus
              autoComplete="email"
              disabled={state === 'loading'}
              required
            />

            {state === 'error' && (
              <p className={styles.error} role="alert">{errorMsg}</p>
            )}

            <button
              type="submit"
              className={styles.submit}
              disabled={state === 'loading' || !email.trim()}
            >
              {state === 'loading'
                ? <span className={styles.spinner} aria-label={t('sending', locale)} />
                : t('send_link', locale)}
            </button>
          </form>
        )}

        <footer className={styles.footer}>{t('no_password', locale)}</footer>
      </div>
    </div>
  );
}
