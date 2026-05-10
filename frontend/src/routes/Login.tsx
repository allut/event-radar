import { useState } from 'react';
import { api, ApiError } from '../api/client';
import { MAGIC_LINK_EXPIRY_MINUTES, type LoginState } from '../constants';
import styles from './Login.module.css';

export default function Login() {
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
      setErrorMsg(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.');
      setState('error');
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <header className={styles.header}>
          <span className={styles.radar} aria-hidden>◉</span>
          <h1 className={styles.brand}>Event Radar</h1>
        </header>

        <p className={styles.tagline}>Your daily five events in Tallinn.</p>

        {state === 'success' ? (
          <div className={styles.success} role="status">
            <div className={styles.checkCircle}>✓</div>
            <p className={styles.successMsg}>
              Check your inbox at <strong>{email}</strong>
            </p>
            <p className={styles.successHint}>The link expires in {MAGIC_LINK_EXPIRY_MINUTES} minutes.</p>
            <button
              className={styles.resend}
              onClick={() => { setState('idle'); setEmail(''); }}
            >
              Use a different address
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className={styles.form} noValidate>
            <label className={styles.label} htmlFor="email">Email address</label>
            <input
              id="email"
              type="email"
              className={styles.input}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
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
                ? <span className={styles.spinner} aria-label="Sending…" />
                : 'Send me a link →'}
            </button>
          </form>
        )}

        <footer className={styles.footer}>No password. No tracking. Just events.</footer>
      </div>
    </div>
  );
}
