import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { t } from '../../i18n';
import {
  API,
  CLAIM_DNS_VERIFICATION_MECHANISMS,
  CLAIM_STATUS_APPROVED,
  CLAIM_STATUS_CANCELLED,
  CLAIM_STATUS_EXPIRED,
  CLAIM_STATUS_PENDING,
  CLAIM_STATUS_REVOKED,
  CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
  CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
  QUERY_KEYS,
  ROUTES,
  UI_STATE,
  type ClaimStatus,
  type ClaimVerificationMechanism,
} from '../../constants';
import { apiErrorMessage, copyToClipboard } from '../../utils';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import PageState from '../../components/PageState';
import SeoTags from '../../components/SeoTags';
import styles from './ClaimPending.module.css';

interface ClaimResponse {
  id: number;
  status: ClaimStatus;
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
  const { id } = useParams<{ id: string }>();
  const [locale, handleLocaleChange] = useLocalLocale();
  const handleLogout = useOrganizerLogout();
  const navigate = useLocaleNavigate();
  const queryClient = useQueryClient();
  const seoMeta = useStaticSeoMeta('organizer_claim_pending_title', locale);
  const [copiedField, setCopiedField] = useState<CopyField | null>(null);
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
    },
    onError: (err) => setActionError(apiErrorMessage(err, t('generic_error', locale))),
  });

  const cancelMutation = useMutation({
    mutationFn: () => organizerApi.post<ClaimResponse>(API.organizerClaimCancel(id as string)),
    onSuccess: (updated) => {
      setActionError('');
      queryClient.setQueryData(queryKey, updated);
    },
    onError: (err) => setActionError(apiErrorMessage(err, t('generic_error', locale))),
  });

  async function handleCopy(field: CopyField, value: string) {
    if (await copyToClipboard(value)) {
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 2000);
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
    eyebrow = t('claim_pending_review_eyebrow', locale);
    title = t('claim_cancelled_title', locale);
    body = t('claim_cancelled_body', locale);
  } else if (claim.status === CLAIM_STATUS_EXPIRED) {
    eyebrow = t('claim_pending_review_eyebrow', locale);
    title = t('claim_expired_title', locale);
    body = t('claim_expired_body', locale);
  } else if (claim.status === CLAIM_STATUS_REVOKED) {
    eyebrow = t('claim_pending_review_eyebrow', locale);
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

  const pillLabel =
    claim.status === CLAIM_STATUS_APPROVED ? t('claim_pill_claimed', locale) : t('claim_pill_pending', locale);
  const pillVariant = claim.status === CLAIM_STATUS_APPROVED ? styles.pillSuccess : '';
  const isPending = claim.status === CLAIM_STATUS_PENDING;

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <div className={styles.card}>
          <span className={`${styles.pill} ${pillVariant}`}>{pillLabel}</span>
          <p className={styles.eyebrow}>{eyebrow}</p>
          <h1 className={styles.heading}>{title}</h1>
          <p className={styles.body}>{body}</p>

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
            {claim.status === 'approved' && (
              <button
                type="button"
                className={styles.primaryBtn}
                onClick={() => navigate(ROUTES.organizerClaimEdit(claim.id))}
              >
                {t('claim_edit_open_cta', locale)}
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

          {isPending && mechanism && mechanism !== CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW && (
            <>
              <hr className={styles.hairline} />
              <p className={styles.hint}>{t('claim_pending_automated_hint', locale)}</p>
            </>
          )}
          {isPending && mechanism === CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW && (
            <>
              <hr className={styles.hairline} />
              <p className={styles.hint}>{t('claim_pending_review_hint', locale)}</p>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
