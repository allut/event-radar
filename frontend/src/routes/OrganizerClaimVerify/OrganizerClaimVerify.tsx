import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { organizerApi, ApiError } from '../../api/client';
import { setOrganizerSignedInHint } from '../../lib/organizerAuth';
import { API, QUERY_KEYS } from '../../constants/api';
import {
  AUTH_REDIRECT_DELAY_MS,
  AUTH_TOKEN_PARAM,
  VERIFY_STATE_TO_KIND,
  type VerifyState,
} from '../../constants/auth';
import { UI_STATE } from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import { t } from '../../i18n';
import { useDelayedAction } from '../../hooks/useDelayedAction';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { useLocalePath } from '../../hooks/useLocalePath';
import { usePathLocale } from '../../hooks/usePathLocale';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import AuthCard from '../../components/AuthCard';
import SeoTags from '../../components/SeoTags';
import styles from './OrganizerClaimVerify.module.css';

interface ClaimLinkVerifyResponse {
  claim: { id: number } | null;
  needs_justification?: boolean;
}

/** Verifies a claim-intent magic link (#413's request-link/verify-link pair,
 * ORGANIZER_CLAIM_VERIFY_PATH) — a distinct frontend route from OrganizerVerify
 * because the claim-link email points here instead, so this component (not
 * the plain organizer sign-in one) is what runs when the organizer opens the
 * link, possibly on a different device than the one that requested it (#409's
 * device-mismatch requirement). Signs the organizer in AND creates the claim
 * in the same request, then lands pre-selected on #415's pending screen. */
export default function OrganizerClaimVerify() {
  const locale = usePathLocale();
  const seoMeta = useStaticSeoMeta('organizer_claim_pending_title', locale);
  const [searchParams] = useSearchParams();
  const navigate = useLocaleNavigate();
  const queryClient = useQueryClient();
  const localePath = useLocalePath();
  const token = searchParams.get(AUTH_TOKEN_PARAM);
  const [state, setState] = useState<VerifyState>(token ? UI_STATE.verifying : UI_STATE.error);
  const [errorMsg, setErrorMsg] = useState(token ? '' : t('no_token', locale));
  // (#428) The one outcome that isn't a plain success/error: sign-in
  // succeeded but this listing resolved to a Series claim, which the
  // signed-out email-capture step never collected a justification for — see
  // organizer_claims.py::verify_claim_link. Sends the organizer to their
  // dashboard, now signed in, to claim it again with a reason.
  const [needsJustification, setNeedsJustification] = useState(false);
  const called = useRef(false);
  const scheduleRedirect = useDelayedAction();

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
        const { claim } = result;
        // Your claims and the dashboard's claims summary count the new claim.
        if (claim) void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerClaims] });
        setOrganizerSignedInHint();
        setState(UI_STATE.success);
        if (result.needs_justification || !claim) {
          setNeedsJustification(true);
          return;
        }
        // `claim` (not `result.claim`) below — TS doesn't carry a property
        // access's narrowing into a closure created later (the scheduleRedirect
        // callback), only a plain local binding's.
        scheduleRedirect(
          () => navigate(ROUTES.organizerClaimPending(claim.id), { replace: true }),
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
  }, [navigate, queryClient, token, locale, localePath, scheduleRedirect]);

  const message =
    state === UI_STATE.verifying ? t('verifying', locale)
    : state === UI_STATE.success
      ? needsJustification ? t('claim_link_needs_justification_message', locale) : t('signed_in', locale)
    : errorMsg;

  return (
    <>
      <SeoTags meta={seoMeta} />
      <AuthCard
        locale={locale}
        kind={VERIFY_STATE_TO_KIND[state]}
        message={message}
        action={state === UI_STATE.error ? (
          <Link to={localePath(ROUTES.organizerLogin)} className={styles.retry}>{t('request_new_link', locale)}</Link>
        ) : needsJustification && (
          <Link to={localePath(ROUTES.organizerDashboard)} className={styles.retry}>
            {t('claim_link_needs_justification_cta', locale)}
          </Link>
        )}
      />
    </>
  );
}
