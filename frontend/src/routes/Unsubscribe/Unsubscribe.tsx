import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { StatusCodes } from 'http-status-codes';
import { api, ApiError } from '../../api/client';
import { getLocale } from '../../lib/auth';
import { t } from '../../i18n';
import { API, ROUTES, UI_STATE, type UnsubscribeState } from '../../constants';
import AuthCard, { type AuthCardKind } from '../../components/AuthCard';
import styles from './Unsubscribe.module.css';

const STATE_TO_KIND: Record<UnsubscribeState, AuthCardKind> = {
  [UI_STATE.working]: 'pending',
  [UI_STATE.success]: 'success',
  [UI_STATE.resubscribed]: 'success',
  [UI_STATE.error]: 'error',
};

export default function Unsubscribe() {
  const locale = getLocale();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const [state, setState] = useState<UnsubscribeState>(token ? UI_STATE.working : UI_STATE.error);
  const [errorMsg, setErrorMsg] = useState(token ? '' : t('unsubscribe.error', locale));
  const [resubscribePending, setResubscribePending] = useState(false);
  const called = useRef(false);

  useEffect(() => {
    if (!token) return;
    if (called.current) return;
    called.current = true;

    async function run(tok: string) {
      try {
        await api.post(`${API.emailUnsubscribe}?token=${encodeURIComponent(tok)}`);
        setState(UI_STATE.success);
      } catch (err) {
        setState(UI_STATE.error);
        setErrorMsg(
          err instanceof ApiError && err.status === StatusCodes.BAD_REQUEST
            ? t('unsubscribe.expired', locale)
            : t('unsubscribe.error', locale)
        );
      }
    }
    void run(token);
  }, [token, locale]);

  async function handleResubscribe() {
    if (!token || resubscribePending) return;
    setResubscribePending(true);
    try {
      await api.post(`${API.emailResubscribe}?token=${encodeURIComponent(token)}`);
      setState(UI_STATE.resubscribed);
    } catch {
      setErrorMsg(t('unsubscribe.error', locale));
    } finally {
      setResubscribePending(false);
    }
  }

  const message =
    state === UI_STATE.working ? t('unsubscribe.working', locale)
    : state === UI_STATE.success ? t('unsubscribe.success', locale)
    : state === UI_STATE.resubscribed ? t('unsubscribe.resubscribed', locale)
    : errorMsg;

  return (
    <AuthCard
      locale={locale}
      kind={STATE_TO_KIND[state]}
      message={message}
      animated={false}
      action={
        state === UI_STATE.success ? (
          <button
            type="button"
            className={styles.resubscribeBtn}
            onClick={() => void handleResubscribe()}
            disabled={resubscribePending}
          >
            {t('unsubscribe.resubscribe', locale)}
          </button>
        ) : state === UI_STATE.error ? (
          <Link to={ROUTES.settings} className={styles.settingsLink}>
            {t('unsubscribe.manage_settings', locale)}
          </Link>
        ) : undefined
      }
    />
  );
}
