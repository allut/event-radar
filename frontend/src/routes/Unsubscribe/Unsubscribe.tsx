import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { StatusCodes } from 'http-status-codes';
import { api, ApiError } from '../../api/client';
import { t } from '../../i18n';
import { API, AUTH_TOKEN_PARAM, ROUTES, UI_STATE, type UnsubscribeState } from '../../constants';
import { withQueryParam } from '../../utils';
import { useLocalePath } from '../../hooks/useLocalePath';
import { usePathLocale } from '../../hooks/usePathLocale';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import AuthCard, { type AuthCardKind } from '../../components/AuthCard';
import SeoTags from '../../components/SeoTags';
import styles from './Unsubscribe.module.css';

const STATE_TO_KIND: Record<UnsubscribeState, AuthCardKind> = {
  [UI_STATE.working]: 'pending',
  [UI_STATE.success]: 'success',
  [UI_STATE.resubscribed]: 'success',
  [UI_STATE.error]: 'error',
};

export default function Unsubscribe() {
  const locale = usePathLocale();
  const localePath = useLocalePath();
  const seoMeta = useStaticSeoMeta('seo_title_unsubscribe', locale);
  const [searchParams] = useSearchParams();
  // Captured once: the reusable 365-day token is stripped from the address bar
  // below, so later renders must not depend on the live query string.
  const [token] = useState(() => searchParams.get(AUTH_TOKEN_PARAM));
  const [state, setState] = useState<UnsubscribeState>(token ? UI_STATE.working : UI_STATE.error);
  const [errorMsg, setErrorMsg] = useState(token ? '' : t('unsubscribe.error', locale));
  const [resubscribePending, setResubscribePending] = useState(false);
  const called = useRef(false);

  useEffect(() => {
    if (!token) return;
    if (called.current) return;
    called.current = true;

    // Keep the long-lived token out of browser history (OWASP audit L-9).
    window.history.replaceState({}, '', localePath(ROUTES.unsubscribe));

    async function run(tok: string) {
      try {
        await api.post(withQueryParam(API.emailUnsubscribe, AUTH_TOKEN_PARAM, tok));
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
  }, [token, locale, localePath]);

  async function handleResubscribe() {
    if (!token || resubscribePending) return;
    setResubscribePending(true);
    try {
      await api.post(withQueryParam(API.emailResubscribe, AUTH_TOKEN_PARAM, token));
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
    <>
      <SeoTags meta={seoMeta} />
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
            <Link to={localePath(ROUTES.settings)} className={styles.settingsLink}>
              {t('unsubscribe.manage_settings', locale)}
            </Link>
          ) : undefined
        }
      />
    </>
  );
}
