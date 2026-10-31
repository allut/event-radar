import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { StatusCodes } from 'http-status-codes';
import { api, ApiError } from '../../api/client';
import { t } from '../../i18n';
import { API } from '../../constants/api';
import { AUTH_TOKEN_PARAM, type UnsubscribeState } from '../../constants/auth';
import { UI_STATE } from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import { withQueryParam } from '../../utils/url';
import { useLocalePath } from '../../hooks/useLocalePath';
import { usePathLocale } from '../../hooks/usePathLocale';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import AuthCard, { type AuthCardKind } from '../../components/AuthCard';
import SeoTags from '../../components/SeoTags';
import styles from './ConsentOff.module.css';

// Same four-state machine as Unsubscribe: `resubscribed` is the undone state.
const STATE_TO_KIND: Record<UnsubscribeState, AuthCardKind> = {
  [UI_STATE.working]: 'pending',
  [UI_STATE.success]: 'success',
  [UI_STATE.resubscribed]: 'success',
  [UI_STATE.error]: 'error',
};

/** One-click Email ad consent withdrawal from the digest's "Stop ads in this
 * email" link. The digest keeps coming. Undo grants consent again. */
export default function ConsentOff() {
  const locale = usePathLocale();
  const localePath = useLocalePath();
  const seoMeta = useStaticSeoMeta('seo_title_consent_off', locale);
  const [searchParams] = useSearchParams();
  // Captured once: the 365-day token is stripped from the address bar below.
  const [token] = useState(() => searchParams.get(AUTH_TOKEN_PARAM));
  const [state, setState] = useState<UnsubscribeState>(token ? UI_STATE.working : UI_STATE.error);
  const [errorMsg, setErrorMsg] = useState(token ? '' : t('unsubscribe.error', locale));
  const [undoPending, setUndoPending] = useState(false);
  const called = useRef(false);

  useEffect(() => {
    if (!token) return;
    if (called.current) return;
    called.current = true;

    window.history.replaceState({}, '', localePath(ROUTES.consentOff));

    async function run(tok: string) {
      try {
        await api.post(withQueryParam(API.emailConsentOff, AUTH_TOKEN_PARAM, tok));
        setState(UI_STATE.success);
      } catch (err) {
        setState(UI_STATE.error);
        setErrorMsg(
          err instanceof ApiError && err.status === StatusCodes.BAD_REQUEST
            ? t('consent_off.expired', locale)
            : t('unsubscribe.error', locale)
        );
      }
    }
    void run(token);
  }, [token, locale, localePath]);

  async function handleUndo() {
    if (!token || undoPending) return;
    setUndoPending(true);
    try {
      await api.post(withQueryParam(API.emailConsentOn, AUTH_TOKEN_PARAM, token));
      setState(UI_STATE.resubscribed);
    } catch {
      setErrorMsg(t('unsubscribe.error', locale));
      setState(UI_STATE.error);
    } finally {
      setUndoPending(false);
    }
  }

  const message =
    state === UI_STATE.working ? t('consent_off.working', locale)
    : state === UI_STATE.success ? t('consent_off.done', locale)
    : state === UI_STATE.resubscribed ? t('consent_off.undone', locale)
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
          state === UI_STATE.working ? undefined : (
            <>
              {state === UI_STATE.success && (
                <button
                  type="button"
                  className={styles.undoBtn}
                  onClick={() => void handleUndo()}
                  disabled={undoPending}
                >
                  {t('consent_off.undo', locale)}
                </button>
              )}
              <Link to={localePath(ROUTES.settings)} className={styles.settingsLink}>
                {t('unsubscribe.manage_settings', locale)}
              </Link>
            </>
          )
        }
      />
    </>
  );
}
