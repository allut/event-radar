import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import { setOrganizerToken } from '../../lib/organizerAuth';
import { getLocale } from '../../lib/auth';
import { AUTH_REDIRECT_DELAY_MS, UI_STATE, type VerifyState } from '../../constants';
import { t } from '../../i18n';
import styles from './OrganizerVerify.module.css';

interface VerifyResponse {
  session_token: string;
}

export default function OrganizerVerify() {
  const locale = getLocale();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get('token');
  const [state, setState] = useState<VerifyState>(token ? UI_STATE.verifying : UI_STATE.error);
  const [errorMsg, setErrorMsg] = useState(token ? '' : t('no_token', locale));
  const called = useRef(false);

  useEffect(() => {
    if (!token) return;
    if (called.current) return;
    called.current = true;

    // Strip the single-use token from the address bar before the async verify
    // call, same rationale as AuthVerify — see that file for the full comment.
    window.history.replaceState({}, '', '/organizer/verify');

    async function verify(tok: string) {
      try {
        const data = await api.get<VerifyResponse>(
          `/organizer/auth/verify?token=${encodeURIComponent(tok)}`,
          { organizer: true },
        );
        setOrganizerToken(data.session_token);
        setState(UI_STATE.success);
        setTimeout(() => navigate('/organizer/dashboard', { replace: true }), AUTH_REDIRECT_DELAY_MS);
      } catch (err) {
        setState(UI_STATE.error);
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

        {state === UI_STATE.verifying && (
          <div className={styles.status} role="status" aria-live="polite">
            <span className={styles.spinner} aria-label={t('verifying', locale)} />
            <p className={styles.message}>{t('verifying', locale)}</p>
          </div>
        )}

        {state === UI_STATE.success && (
          <div className={styles.status} role="status">
            <div className={styles.check}>✓</div>
            <p className={styles.message}>{t('signed_in', locale)}</p>
          </div>
        )}

        {state === UI_STATE.error && (
          <div className={styles.status} role="alert">
            <div className={styles.errorIcon}>✕</div>
            <p className={styles.message}>{errorMsg}</p>
            <a href="/organizer/login" className={styles.retry}>{t('request_new_link', locale)}</a>
          </div>
        )}
      </div>
    </div>
  );
}
