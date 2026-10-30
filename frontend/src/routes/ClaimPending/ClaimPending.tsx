import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { t, ti } from '../../i18n';
import {
  CLAIM_ADMIN_REVIEW_EXPIRY_DAYS,
  CLAIM_EXPIRY_DAYS,
  CLAIM_KIND_PUBLISHER,
  CLAIM_STATUS_APPROVED,
  CLAIM_STATUS_CANCELLED,
  CLAIM_STATUS_DECLINED,
  CLAIM_STATUS_EXPIRED,
  CLAIM_STATUS_PENDING,
  CLAIM_STATUS_REVOKED,
  CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
} from '../../_generated/sharedConstants';
import { API, QUERY_KEYS } from '../../constants/api';
import {
  CLAIM_DNS_VERIFICATION_MECHANISMS,
  CLAIM_SELF_SERVICE_VERIFICATION_MECHANISMS,
  CLAIM_TERMINAL_STATUSES,
  type ClaimKind,
  type ClaimStatus,
  type ClaimVerificationMechanism,
} from '../../constants/claims';
import { COPY_FEEDBACK_MS, UI_STATE } from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import { apiErrorMessage, copyToClipboard, numericRouteId } from '../../utils';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import PageState from '../../components/PageState';
import SeoTags from '../../components/SeoTags';
import styles from './ClaimPending.module.css';

interface ClaimResponse {
  id: number;
  kind: ClaimKind;
  status: ClaimStatus;
  dormant: boolean;
  verification_mechanism: ClaimVerificationMechanism | null;
  dns_record_name: string | null;
  dns_record_value: string;
  can_recheck: boolean;
}

type CopyField = 'code' | 'record_name' | 'record_value';

/** #415's mechanism-specific pending screen — the third landing spot (after
 * an already-authenticated organizer's claim and a fresh sign-up via
 * OrganizerClaimVerify) every claim-creation path lands on. Reads the claim
 * fresh from the server on every mount so a bookmarked/reopened link always
 * reflects the latest sweep/recheck outcome, not a stale navigation payload. */
export default function ClaimPending() {
  const { id: rawId } = useParams<{ id: string }>();
  const id = numericRouteId(rawId);
  const [locale, handleLocaleChange] = useLocalLocale();
  const handleLogout = useOrganizerLogout();
  const navigate = useLocaleNavigate();
  const queryClient = useQueryClient();
  const seoMeta = useStaticSeoMeta('organizer_claim_pending_title', locale);
  const [copiedField, setCopiedField] = useState<CopyField | null>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(copyTimer.current), []);
  const [actionError, setActionError] = useState('');

  const queryKey = [QUERY_KEYS.organizerClaim, id];
  const { data: claim, isLoading, isError } = useQuery({
    queryKey,
    queryFn: () => organizerApi.get<ClaimResponse>(API.organizerClaim(id as string)),
    enabled: !!id,
  });

  const recheckMutation = useMutation({
    mutationFn: () => organizerApi.post<ClaimResponse>(API.organizerClaimRecheck(id as string)),
    onSuccess: (updated) => {
      setActionError('');
      queryClient.setQueryData(queryKey, updated);
      // Your claims and the dashboard's claims summary show this status.
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerClaims] });
    },
    onError: (err) => setActionError(apiErrorMessage(err, t('generic_error', locale))),
  });

  const cancelMutation = useMutation({
    mutationFn: () => organizerApi.post<ClaimResponse>(API.organizerClaimCancel(id as string)),
    onSuccess: (updated) => {
      setActionError('');
      queryClient.setQueryData(queryKey, updated);
      // Your claims and the dashboard's claims summary show this status.
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerClaims] });
    },
    onError: (err) => setActionError(apiErrorMessage(err, t('generic_error', locale))),
  });

  async function handleCopy(field: CopyField, value: string) {
    if (await copyToClipboard(value)) {
      setCopiedField(field);
      clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopiedField(null), COPY_FEEDBACK_MS);
    }
  }

  function handleCancel() {
    if (!window.confirm(t('claim_cancel_confirm', locale))) return;
    cancelMutation.mutate();
  }

  if (isLoading) {
    return (
      <div className={styles.page}>
        <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />
        <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
      </div>
    );
  }

  if (isError || !claim) {
    return (
      <div className={styles.page}>
        <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />
        <PageState kind={UI_STATE.error} message={t('generic_error', locale)} inline />
      </div>
    );
  }

  const mechanism = claim.verification_mechanism;
  let eyebrow: string;
  let title: string;
  let body: string;

  if (claim.status === CLAIM_STATUS_APPROVED) {
    eyebrow = t('claim_pending_approved_eyebrow', locale);
    title = t('claim_pending_approved_title', locale);
    body = t('claim_pending_approved_body', locale);
  } else if (claim.status === CLAIM_STATUS_CANCELLED) {
    eyebrow = t('claim_pending_closed_eyebrow', locale);
    title = t('claim_cancelled_title', locale);
    body = t('claim_cancelled_body', locale);
  } else if (claim.status === CLAIM_STATUS_EXPIRED) {
    eyebrow = t('claim_pending_closed_eyebrow', locale);
    title = t('claim_expired_title', locale);
    const expiredDays =
      mechanism && CLAIM_SELF_SERVICE_VERIFICATION_MECHANISMS.has(mechanism)
        ? CLAIM_EXPIRY_DAYS
        : CLAIM_ADMIN_REVIEW_EXPIRY_DAYS;
    body = ti('claim_expired_body', locale, { days: String(expiredDays) });
  } else if (claim.status === CLAIM_STATUS_DECLINED) {
    eyebrow = t('claim_pending_closed_eyebrow', locale);
    title = t('claim_declined_title', locale);
    body = t('claim_declined_body', locale);
  } else if (claim.status === CLAIM_STATUS_REVOKED) {
    eyebrow = t('claim_pending_closed_eyebrow', locale);
    title = t('claim_revoked_title', locale);
    body = t('claim_revoked_body', locale);
  } else if (mechanism === CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN) {
    eyebrow = t('claim_pending_fienta_eyebrow', locale);
    title = t('claim_pending_fienta_title', locale);
    body = t('claim_pending_fienta_body', locale);
  } else if (mechanism && CLAIM_DNS_VERIFICATION_MECHANISMS.has(mechanism)) {
    eyebrow = t('claim_pending_dns_eyebrow', locale);
    title = t('claim_pending_dns_title', locale);
    body = t('claim_pending_dns_body', locale);
  } else {
    eyebrow = t('claim_pending_review_eyebrow', locale);
    title = t('claim_pending_review_title', locale);
    body = t('claim_pending_review_body', locale);
  }

  const isTerminal = CLAIM_TERMINAL_STATUSES.has(claim.status);
  const pillLabel = claim.status === CLAIM_STATUS_APPROVED ? t('claim_pill_claimed', locale) : t('claim_pill_pending', locale);
  const pillVariant = claim.status === CLAIM_STATUS_APPROVED ? styles.pillSuccess : '';
  const isPending = claim.status === CLAIM_STATUS_PENDING;

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <div className={styles.card}>
          {!isTerminal && <span className={`${styles.pill} ${pillVariant}`}>{pillLabel}</span>}
          <p className={styles.eyebrow}>{eyebrow}</p>
          <h1 className={styles.heading}>{title}</h1>
          <p className={styles.body}>{body}</p>

          {claim.status === CLAIM_STATUS_APPROVED && claim.dormant && (
            <p className={styles.dormantNote}>{t('claim_pending_dormant_note', locale)}</p>
          )}

          {isPending && mechanism === CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN && (
            <div className={styles.field}>
              <span className={styles.fieldLabel}>{t('claim_pending_field_code', locale)}</span>
              <div className={styles.codeBlock}>
                <span className={styles.codeValue}>{claim.dns_record_value}</span>
                <button
                  type="button"
                  className={styles.copyBtn}
                  onClick={() => handleCopy('code', claim.dns_record_value)}
                >
                  {copiedField === 'code' ? t('claim_copied', locale) : t('claim_copy', locale)}
                </button>
              </div>
            </div>
          )}

          {isPending && mechanism && CLAIM_DNS_VERIFICATION_MECHANISMS.has(mechanism) && claim.dns_record_name && (
            <>
              <div className={styles.field}>
                <span className={styles.fieldLabel}>{t('claim_pending_field_record_name', locale)}</span>
                <div className={styles.codeBlock}>
                  <span className={styles.codeValue}>{claim.dns_record_name}</span>
                  <button
                    type="button"
                    className={styles.copyBtn}
                    onClick={() => handleCopy('record_name', claim.dns_record_name as string)}
                  >
                    {copiedField === 'record_name' ? t('claim_copied', locale) : t('claim_copy', locale)}
                  </button>
                </div>
              </div>
              <div className={styles.field}>
                <span className={styles.fieldLabel}>{t('claim_pending_field_record_value', locale)}</span>
                <div className={styles.codeBlock}>
                  <span className={styles.codeValue}>{claim.dns_record_value}</span>
                  <button
                    type="button"
                    className={styles.copyBtn}
                    onClick={() => handleCopy('record_value', claim.dns_record_value)}
                  >
                    {copiedField === 'record_value' ? t('claim_copied', locale) : t('claim_copy', locale)}
                  </button>
                </div>
              </div>
            </>
          )}

          {actionError && <p className={styles.error} role="alert">{actionError}</p>}

          <div className={styles.actions}>
            {claim.status === CLAIM_STATUS_APPROVED && (
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={() => navigate(ROUTES.organizerClaimEdit(claim.id))}
                disabled={claim.dormant}
              >
                {t('claim_edit_open_cta', locale)}
              </button>
            )}
            {claim.status === CLAIM_STATUS_APPROVED && claim.kind === CLAIM_KIND_PUBLISHER && (
              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={() => navigate(ROUTES.organizerClaimEvents(claim.id))}
              >
                {t('claim_events_view_cta', locale)}
              </button>
            )}
            {isPending && claim.can_recheck && (
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={() => recheckMutation.mutate()}
                disabled={recheckMutation.isPending}
              >
                {recheckMutation.isPending ? t('claim_checking', locale) : t('claim_check_now', locale)}
              </button>
            )}
            {isPending && (
              <button
                type="button"
                className={styles.cancelBtn}
                onClick={handleCancel}
                disabled={cancelMutation.isPending}
              >
                {t('claim_cancel_this', locale)}
              </button>
            )}
          </div>

          {isPending && mechanism && CLAIM_SELF_SERVICE_VERIFICATION_MECHANISMS.has(mechanism) && (
            <>
              <hr className={styles.hairline} />
              <p className={styles.hint}>
                {ti('claim_pending_automated_hint', locale, { days: String(CLAIM_EXPIRY_DAYS) })}
              </p>
            </>
          )}
          {isPending && mechanism && !CLAIM_SELF_SERVICE_VERIFICATION_MECHANISMS.has(mechanism) && (
            <>
              <hr className={styles.hairline} />
              <p className={styles.hint}>
                {ti('claim_pending_review_hint', locale, { days: String(CLAIM_ADMIN_REVIEW_EXPIRY_DAYS) })}
              </p>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
