import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { setToken } from '../lib/auth';
import { AUTH_REDIRECT_DELAY_MS, type VerifyState } from '../constants';
import styles from './AuthVerify.module.css';

interface VerifyResponse {
  session_token: string;
}

interface MeResponse {
  has_personas: boolean;
}

export default function AuthVerify() {
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
      setErrorMsg('No sign-in token found in the URL. Please request a new link.');
      return;
    }

    api.get<VerifyResponse>(`/auth/verify?token=${encodeURIComponent(token)}`)
      .then(async (data) => {
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
      })
      .catch((err) => {
        setState('error');
        setErrorMsg(
          err instanceof ApiError
            ? err.message
            : 'Verification failed. The link may have expired.'
        );
      });
  }, [navigate, searchParams]);

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <span className={styles.radar} aria-hidden>◉</span>
        <h1 className={styles.brand}>Event Radar</h1>

        {state === 'verifying' && (
          <div className={styles.status} role="status" aria-live="polite">
            <span className={styles.spinner} aria-label="Verifying…" />
            <p className={styles.message}>Verifying your sign-in link…</p>
          </div>
        )}

        {state === 'success' && (
          <div className={styles.status} role="status">
            <div className={styles.check}>✓</div>
            <p className={styles.message}>Signed in! Redirecting…</p>
          </div>
        )}

        {state === 'error' && (
          <div className={styles.status} role="alert">
            <div className={styles.errorIcon}>✕</div>
            <p className={styles.message}>{errorMsg}</p>
            <a href="/login" className={styles.retry}>Request a new link →</a>
          </div>
        )}
      </div>
    </div>
  );
}
