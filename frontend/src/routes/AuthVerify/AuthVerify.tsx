import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import { setToken, getLocale } from '../../lib/auth';
import { AUTH_REDIRECT_DELAY_MS, type VerifyState } from '../../constants';
import { t } from '../../i18n';
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
  const token = searchParams.get('token');
  const [state, setState] = useState<VerifyState>(token ? 'verifying' : 'error');
  const [errorMsg, setErrorMsg] = useState(token ? '' : t('no_token', locale));
  const called = useRef(false);

  useEffect(() => {
    if (!token) return;
    if (called.current) return;
    called.current = true;

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
    void verify(token);
  }, [navigate, token, locale]);

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
