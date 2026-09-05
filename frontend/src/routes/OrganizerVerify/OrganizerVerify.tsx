import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { organizerApi, ApiError } from '../../api/client';
import { setOrganizerSignedInHint } from '../../lib/organizerAuth';
import { getLocale } from '../../lib/auth';
import { syncAccountTheme } from '../../lib/theme';
import { API, AUTH_REDIRECT_DELAY_MS, ROUTES, UI_STATE, VERIFY_STATE_TO_KIND, type VerifyState } from '../../constants';
import { t } from '../../i18n';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import AuthCard from '../../components/AuthCard';
import SeoTags from '../../components/SeoTags';
import styles from './OrganizerVerify.module.css';

interface OrganizerProfileResponse {
  theme_preference: 'light' | 'dark' | null;
}

export default function OrganizerVerify() {
  const locale = getLocale();
  const seoMeta = useStaticSeoMeta('seo_title_organizer_verify', locale);
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
    // call, same rationale as AuthVerify — see that file for the full comment.
    window.history.replaceState({}, '', localePath(ROUTES.organizerVerify));

    async function verify(tok: string) {
      try {
        await organizerApi.post(API.organizerAuthVerify, { token: tok });
        setOrganizerSignedInHint();
        setState(UI_STATE.success);
        try {
          const profile = await organizerApi.get<OrganizerProfileResponse>(API.organizerProfile);
          syncAccountTheme(profile.theme_preference, (theme) =>
            organizerApi.patch(API.organizerProfile, { theme_preference: theme })
          );
        } catch {
          // GET /organizer/profile failure is non-fatal — sign-in already succeeded
        }
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
          <Link to={localePath(ROUTES.organizerLogin)} className={styles.retry}>{t('request_new_link', locale)}</Link>
        )}
      />
    </>
  );
}
