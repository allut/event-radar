import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import { setToken, getLocale } from '../../lib/auth';
import { AUTH_REDIRECT_DELAY_MS, UI_STATE, type VerifyState } from '../../constants';
import { t } from '../../i18n';
import AuthCard, { type AuthCardKind } from '../../components/AuthCard';
import styles from './AuthVerify.module.css';

interface VerifyResponse {
  session_token: string;
}

interface MeResponse {
  has_personas: boolean;
}

const STATE_TO_KIND: Record<VerifyState, AuthCardKind> = {
  [UI_STATE.verifying]: 'pending',
  [UI_STATE.success]: 'success',
  [UI_STATE.error]: 'error',
};

export default function AuthVerify() {
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
    // call — otherwise it persists in browser history (and any history-sync
    // service) for as long as the entry survives, extending its exposure well
    // past the short window a network observer would have.
    window.history.replaceState({}, '', '/auth/verify');

    async function verify(tok: string) {
      try {
        const data = await api.get<VerifyResponse>(`/auth/verify?token=${encodeURIComponent(tok)}`);
        setToken(data.session_token);
        setState(UI_STATE.success);
        let dest = '/onboarding';
        try {
          const me = await api.get<MeResponse>('/auth/me');
          if (me.has_personas) dest = '/';
        } catch {
          // /auth/me failure is non-fatal — fall back to /onboarding
        }
        setTimeout(() => navigate(dest, { replace: true }), AUTH_REDIRECT_DELAY_MS);
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

  const message =
    state === UI_STATE.verifying ? t('verifying', locale)
    : state === UI_STATE.success ? t('signed_in', locale)
    : errorMsg;

  return (
    <AuthCard
      locale={locale}
      kind={STATE_TO_KIND[state]}
      message={message}
      action={state === UI_STATE.error && (
        <Link to="/login" className={styles.retry}>{t('request_new_link', locale)}</Link>
      )}
    />
  );
}
