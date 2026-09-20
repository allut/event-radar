import { useState } from 'react';
import { organizerApi } from '../../api/client';
import { API, ROUTES, UI_STATE } from '../../constants';
import { t } from '../../i18n';
import { apiErrorMessage } from '../../utils';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useOrganizerAuth } from '../../hooks/useOrganizerAuth';
import MagicLinkForm from '../MagicLinkForm';
import styles from './ClaimStrip.module.css';

export type EventClaimStatus = 'unclaimed' | 'pending' | 'claimed';

interface ClaimPillProps {
  status: 'pending' | 'claimed';
  locale: string;
}

/** Sits beside the event date/time — the public page's read-only marker once
 * an event is no longer claimable via this CTA (#414: "cross-surface
 * retirement" once a claim is pending or granted). */
export function ClaimPill({ status, locale }: ClaimPillProps) {
  return (
    <span className={styles.pill}>
      {t(status === 'claimed' ? 'claim_pill_claimed' : 'claim_pill_pending', locale)}
    </span>
  );
}

interface ClaimPanelProps {
  eventId: number;
  locale: string;
}

/** The "is this your event?" discovery surface (#414) — always shown for an
 * unclaimed event, gated only on organizer-auth state: a signed-in
 * *organizer* claims in one click; a signed-out visitor or a signed-in
 * *consumer* (deliberately treated the same — no gating on consumer auth)
 * gets an inline email-capture step whose magic link carries the claim
 * intent (event_id) through sign-in, per #413's claim-link tokens. */
export function ClaimPanel({ eventId, locale }: ClaimPanelProps) {
  const organizerAuthed = useOrganizerAuth();
  const localePath = useLocalePath();
  const [state, setState] = useState<'idle' | 'loading' | 'email-form' | 'created' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState('');
  const [createdStatus, setCreatedStatus] = useState<'pending' | 'approved'>('pending');

  async function handleClaimClick() {
    if (!organizerAuthed) {
      setState('email-form');
      return;
    }
    setState('loading');
    setErrorMsg('');
    try {
      const claim = await organizerApi.post<{ status: 'pending' | 'approved' }>(
        API.organizerClaims,
        { event_id: eventId },
      );
      setCreatedStatus(claim.status);
      setState('created');
    } catch (err) {
      setErrorMsg(apiErrorMessage(err, t('generic_error', locale)));
      setState('error');
    }
  }

  if (state === 'created') {
    return (
      <section className={styles.panel}>
        <h2 className={styles.heading}>
          {t(createdStatus === 'approved' ? 'claim_pill_claimed' : 'claim_pill_pending', locale)}
        </h2>
        <p className={styles.body}>
          <a href={localePath(ROUTES.organizerDashboard)} className={styles.dashboardLink}>
            {t('organizer_dashboard_title', locale)}
          </a>
        </p>
      </section>
    );
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
