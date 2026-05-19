import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { setToken, getLocale } from '../lib/auth';
import { AUTH_REDIRECT_DELAY_MS, type VerifyState } from '../constants';
import { t } from '../i18n';
import styles from './AuthVerify.module.css';

interface VerifyResponse {
  session_token: string;
}

interface MeResponse {
  has_personas: boolean;
}

export default function AuthVerify() {
  const locale = getLocale();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [state, setState] = useState<VerifyState>('verifying');
  const [errorMsg, setErrorMsg] = useState('');
  const called = useRef(false);

  useEffect(() => {
    if (called.current) return;
    called.current = true;

    const token = searchParams.get('token');
    if (!token) {
      setState('error');
      setErrorMsg(t('no_token', locale));
      return;
    }

    async function verify(tok: string) {
      try {
        const data = await api.get<VerifyResponse>(`/auth/verify?token=${encodeURIComponent(tok)}`);
        setToken(data.session_token);
        setState('success');
        let dest = '/onboarding';
        try {
          const me = await api.get<MeResponse>('/auth/me');
          if (me.has_personas) dest = '/';
        } catch {
          // /auth/me failure is non-fatal — fall back to /onboarding
        }
        setTimeout(() => navigate(dest, { replace: true }), AUTH_REDIRECT_DELAY_MS);
      } catch (err) {
        setState('error');
        setErrorMsg(
          err instanceof ApiError
            ? err.message
            : t('verify_failed', locale)
        );
      }
    }
    verify(token);
  }, [navigate, searchParams]);

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <span className={styles.radar} aria-hidden>◉</span>
        <h1 className={styles.brand}>{t('brand', locale)}</h1>

        {state === 'verifying' && (
          <div className={styles.status} role="status" aria-live="polite">
            <span className={styles.spinner} aria-label={t('verifying', locale)} />
            <p className={styles.message}>{t('verifying', locale)}</p>
          </div>
        )}

        {state === 'success' && (
          <div className={styles.status} role="status">
            <div className={styles.check}>✓</div>
            <p className={styles.message}>{t('signed_in', locale)}</p>
          </div>
        )}

        {state === 'error' && (
          <div className={styles.status} role="alert">
            <div className={styles.errorIcon}>✕</div>
            <p className={styles.message}>{errorMsg}</p>
            <a href="/login" className={styles.retry}>{t('request_new_link', locale)}</a>
          </div>
        )}
      </div>
    </div>
  );
}
