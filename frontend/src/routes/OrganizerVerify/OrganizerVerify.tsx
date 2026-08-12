import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { organizerApi, ApiError } from '../../api/client';
import { setOrganizerSignedInHint } from '../../lib/organizerAuth';
import { getLocale } from '../../lib/auth';
import { API, AUTH_REDIRECT_DELAY_MS, ROUTES, UI_STATE, type VerifyState } from '../../constants';
import { t } from '../../i18n';
import AuthCard, { type AuthCardKind } from '../../components/AuthCard';
import styles from './OrganizerVerify.module.css';

const STATE_TO_KIND: Record<VerifyState, AuthCardKind> = {
  [UI_STATE.verifying]: 'pending',
  [UI_STATE.success]: 'success',
  [UI_STATE.error]: 'error',
};

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
    window.history.replaceState({}, '', ROUTES.organizerVerify);

    async function verify(tok: string) {
      try {
        await organizerApi.post(API.organizerAuthVerify, { token: tok });
        setOrganizerSignedInHint();
        setState(UI_STATE.success);
        setTimeout(() => navigate(ROUTES.organizerDashboard, { replace: true }), AUTH_REDIRECT_DELAY_MS);
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
        <Link to={ROUTES.organizerLogin} className={styles.retry}>{t('request_new_link', locale)}</Link>
      )}
    />
  );
}
