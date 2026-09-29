import { useState } from 'react';
import { organizerApi } from '../../api/client';
import { API, EVENT_CLAIM_STATUS_CLAIMED, EVENT_CLAIM_STATUS_PENDING, ROUTES, UI_STATE } from '../../constants';
import { t } from '../../i18n';
import { apiErrorMessage, isClaimJustificationRequiredError } from '../../utils';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { useOrganizerAuth } from '../../hooks/useOrganizerAuth';
import MagicLinkForm from '../MagicLinkForm';
import styles from './ClaimStrip.module.css';

interface ClaimPillProps {
  status: typeof EVENT_CLAIM_STATUS_PENDING | typeof EVENT_CLAIM_STATUS_CLAIMED;
  locale: string;
}

/** Sits beside the event date/time — the public page's read-only marker once
 * an event is no longer claimable via this CTA (#414: "cross-surface
 * retirement" once a claim is pending or granted). `status="claimed"` is
 * public (backs "Organizer-verified" for any viewer). `status="pending"` is
 * claimant-only (#451): GET /events/{id}'s `claim_status` never carries
 * "pending" — it collapses into "unclaimed" for every caller, organizer or
 * not, so a rival claimant or a browser that merely once saw an organizer
 * sign-in can't read it off the public payload. The caller's own EventDetail
 * decides whether to render this with `status="pending"` only after a
 * separate organizer-scoped call (GET /organizer/claims/for-event/{id})
 * confirms the *caller* holds the pending claim, not just that one exists on
 * the target. */
export function ClaimPill({ status, locale }: ClaimPillProps) {
  return (
    <span className={styles.pill}>
      {t(status === EVENT_CLAIM_STATUS_CLAIMED ? 'claim_pill_claimed' : 'claim_pill_pending', locale)}
    </span>
  );
}

interface ClaimPanelProps {
  eventId: number;
  locale: string;
}

/** The "is this your event?" discovery surface (#414) — shown for an
 * unclaimed event and, per #441/ADR 0004, also for a target that only has
 * pending claim(s) (a rival claimant can still start proving ownership;
 * hidden only once a claim is approved). Gated only on organizer-auth
 * state: a signed-in *organizer* claims in one click; a signed-out visitor
 * or a signed-in *consumer* (deliberately treated the same — no gating on
 * consumer auth) gets an inline email-capture step whose magic link
 * carries the claim intent (event_id) through sign-in, per #413's
 * claim-link tokens. */
export function ClaimPanel({ eventId, locale }: ClaimPanelProps) {
  const organizerAuthed = useOrganizerAuth();
  const navigate = useLocaleNavigate();
  const [state, setState] = useState<'idle' | 'loading' | 'email-form' | 'error' | 'needs-justification'>('idle');
  const [errorMsg, setErrorMsg] = useState('');
  const [justification, setJustification] = useState('');

  async function submitClaim(withJustification?: string) {
    setState('loading');
    setErrorMsg('');
    try {
      const claim = await organizerApi.post<{ id: number }>(API.organizerClaims, {
        event_id: eventId,
        justification: withJustification,
      });
      navigate(ROUTES.organizerClaimPending(claim.id));
    } catch (err) {
      if (isClaimJustificationRequiredError(err)) {
        setState('needs-justification');
        return;
      }
      setErrorMsg(apiErrorMessage(err, t('generic_error', locale)));
      setState('error');
    }
  }

  function handleClaimClick() {
    if (!organizerAuthed) {
      setState('email-form');
      return;
    }
    void submitClaim();
  }

  return (
    <section className={styles.panel}>
      <h2 className={styles.heading}>{t('claim_strip_heading', locale)}</h2>

      {state === 'email-form' ? (
        <MagicLinkForm
          locale={locale}
          requestPath={API.organizerClaimLinkRequest}
          organizer
          emailFieldId="claim-email"
          extraBody={{ event_id: eventId }}
        />
      ) : state === 'needs-justification' ? (
        <>
          <p className={styles.body}>{t('claim_justification_prompt', locale)}</p>
          <textarea
            className={styles.justifyInput}
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            placeholder={t('claim_justification_placeholder', locale)}
          />
          <button
            type="button"
            className={styles.cta}
            onClick={() => void submitClaim(justification.trim())}
            disabled={!justification.trim()}
          >
            {t('claim_justification_submit', locale)}
          </button>
        </>
      ) : (
        <>
          <p className={styles.body}>{t('claim_strip_body', locale)}</p>
          {state === UI_STATE.error && (
            <p className={styles.error} role="alert">{errorMsg}</p>
          )}
          <button
            type="button"
            className={styles.cta}
            onClick={handleClaimClick}
            disabled={state === 'loading'}
          >
            {t('claim_strip_cta', locale)}
          </button>
        </>
      )}
    </section>
  );
}
