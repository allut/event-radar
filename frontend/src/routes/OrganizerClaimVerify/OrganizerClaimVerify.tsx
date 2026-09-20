import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { organizerApi, ApiError } from '../../api/client';
import { setOrganizerSignedInHint } from '../../lib/organizerAuth';
import { getLocale } from '../../lib/auth';
import { API, AUTH_REDIRECT_DELAY_MS, AUTH_TOKEN_PARAM, ROUTES, UI_STATE, VERIFY_STATE_TO_KIND, type VerifyState } from '../../constants';
import { t } from '../../i18n';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import AuthCard from '../../components/AuthCard';
import SeoTags from '../../components/SeoTags';
import styles from './OrganizerClaimVerify.module.css';

interface ClaimLinkVerifyResponse {
  claim: { id: number };
}

/** Verifies a claim-intent magic link (#413's request-link/verify-link pair,
 * ORGANIZER_CLAIM_VERIFY_PATH) — a distinct frontend route from OrganizerVerify
 * because the claim-link email points here instead, so this component (not
 * the plain organizer sign-in one) is what runs when the organizer opens the
 * link, possibly on a different device than the one that requested it (#409's
 * device-mismatch requirement). Signs the organizer in AND creates the claim
 * in the same request, then lands pre-selected on #415's pending screen. */
export default function OrganizerClaimVerify() {
  const locale = getLocale();
  const seoMeta = useStaticSeoMeta('organizer_claim_pending_title', locale);
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
    // call, same rationale as AuthVerify/OrganizerVerify.
    window.history.replaceState({}, '', localePath(ROUTES.organizerClaimVerify));

    async function verify(tok: string) {
      try {
        const result = await organizerApi.post<ClaimLinkVerifyResponse>(
          API.organizerClaimLinkVerify,
          { token: tok },
        );
        setOrganizerSignedInHint();
        setState(UI_STATE.success);
        setTimeout(
          () => navigate(ROUTES.organizerClaimPending(result.claim.id), { replace: true }),
          AUTH_REDIRECT_DELAY_MS,
        );
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
