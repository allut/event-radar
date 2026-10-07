import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import { setSignedInHint } from '../../lib/auth';
import { API, AUTH_REDIRECT_DELAY_MS, AUTH_TOKEN_PARAM, ROUTES, UI_STATE, VERIFY_STATE_TO_KIND, type VerifyState } from '../../constants';
import { t } from '../../i18n';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { useLocalePath } from '../../hooks/useLocalePath';
import { usePathLocale } from '../../hooks/usePathLocale';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import AuthCard from '../../components/AuthCard';
import SeoTags from '../../components/SeoTags';
import styles from './AuthVerify.module.css';

interface MeResponse {
  has_personas: boolean;
}

export default function AuthVerify() {
  const locale = usePathLocale();
  const seoMeta = useStaticSeoMeta('seo_title_auth_verify', locale);
  const [searchParams] = useSearchParams();
  const navigate = useLocaleNavigate();
  const localePath = useLocalePath();
  const token = searchParams.get(AUTH_TOKEN_PARAM);
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
    window.history.replaceState({}, '', localePath(ROUTES.authVerify));

    async function verify(tok: string) {
      try {
        await api.post(API.authVerify, { token: tok });
        setSignedInHint();
        setState(UI_STATE.success);
        let dest: string = ROUTES.onboarding;
        try {
          const me = await api.get<MeResponse>(API.authMe);
          if (me.has_personas) dest = ROUTES.home;
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
  }, [navigate, token, locale, localePath]);

  const message =
    state === UI_STATE.verifying ? t('verifying', locale)
    : state === UI_STATE.success ? t('signed_in', locale)
    : errorMsg;

  return (
    <>
      <SeoTags meta={seoMeta} />
      <AuthCard
        locale={locale}
        kind={VERIFY_STATE_TO_KIND[state]}
        message={message}
        action={state === UI_STATE.error && (
          <Link to={localePath(ROUTES.login)} className={styles.retry}>{t('request_new_link', locale)}</Link>
        )}
      />
    </>
  );
}
