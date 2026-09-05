import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import { setSignedInHint, getLocale } from '../../lib/auth';
import { getThemePreference, setThemePreference } from '../../lib/theme';
import { API, AUTH_REDIRECT_DELAY_MS, ROUTES, UI_STATE, VERIFY_STATE_TO_KIND, type VerifyState } from '../../constants';
import { t } from '../../i18n';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import AuthCard from '../../components/AuthCard';
import SeoTags from '../../components/SeoTags';
import styles from './AuthVerify.module.css';

interface MeResponse {
  has_personas: boolean;
  theme_preference: 'light' | 'dark' | null;
}

export default function AuthVerify() {
  const locale = getLocale();
  const seoMeta = useStaticSeoMeta('seo_title_auth_verify', locale);
  const [searchParams] = useSearchParams();
  const navigate = useLocaleNavigate();
  const localePath = useLocalePath();
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
          if (me.theme_preference === 'light' || me.theme_preference === 'dark') {
            // Account preference already exists — it wins and isn't
            // overwritten. Mirror it into localStorage so the local-only
            // pre-paint resolution (no account fetch on every page load)
            // keeps reflecting it on subsequent visits from this device.
            setThemePreference(me.theme_preference);
          } else {
            // No account preference yet — seed it from an explicit local
            // override, if one was set before sign-in. "system"/unset has
            // nothing worth seeding.
            const local = getThemePreference();
            if (local === 'light' || local === 'dark') {
              void api.patch(API.me, { theme_preference: local }).catch(() => {
                // Non-fatal — account sync isn't required for sign-in to succeed.
              });
            }
          }
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
