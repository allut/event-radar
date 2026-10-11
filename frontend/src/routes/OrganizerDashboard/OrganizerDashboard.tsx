import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useLocalePath } from '../../hooks/useLocalePath';
import { t } from '../../i18n';
import { apiErrorMessage, formatEventTime, withLocaleQuery, withQueryParam } from '../../utils';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import OrganizerProfileNudge from '../../components/OrganizerProfileNudge';
import ClaimEventPicker from '../../components/ClaimEventPicker';
import PageState from '../../components/PageState';
import EmptyState from '../../components/EmptyState';
import Toast from '../../components/Toast';
import { useToast } from '../../hooks/useToast';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { API, QUERY_KEYS, PAGE_PARAM } from '../../constants/api';
import {
  CLAIM_KIND_PUBLISHER,
  CLAIM_STATUS_APPROVED,
  type ClaimKind,
  type ClaimStatus,
} from '../../constants/claims';
import { UI_STATE } from '../../constants/core';
import { ORGANIZER_EVENTS_PAGE_SIZE } from '../../constants/organizer';
import { ROUTES } from '../../constants/routes';
import SeoTags from '../../components/SeoTags';
import styles from './OrganizerDashboard.module.css';

interface OrganizerEvent {
  id: number;
  slug: string;
  title: string;
  starts_at: string;
  status: string;
  needs_review: boolean;
}

interface OrganizerEventsResponse {
  events: OrganizerEvent[];
  limit: number;
  offset: number;
}

interface OwnClaim {
  id: number;
  kind: ClaimKind;
  status: ClaimStatus;
  verification_mechanism: string | null;
  dormant: boolean;
  publisher_name: string | null;
  event_id: number | null;
  event_title: string | null;
  created_at: string;
  resolved_at: string | null;
}

interface OwnClaimsResponse {
  claims: OwnClaim[];
}

export default function OrganizerDashboard() {
  const [locale, handleLocaleChange] = useLocalLocale();
  const localePath = useLocalePath();
  const handleLogout = useOrganizerLogout();
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const seoMeta = useStaticSeoMeta('organizer_dashboard_title', locale);

  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.organizerEvents, locale],
    queryFn: () =>
      organizerApi.get<OrganizerEventsResponse>(
        withLocaleQuery(
          withQueryParam(API.organizerEvents, PAGE_PARAM.limit, String(ORGANIZER_EVENTS_PAGE_SIZE)),
          locale,
        ),
      ),
  });

  const deleteMutation = useMutation({
    mutationFn: (eventId: number) => organizerApi.delete(API.organizerEvent(eventId)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerEvents] });
      showToast(UI_STATE.success, t('organizer_delete_success', locale));
    },
    onError: (err) => {
      showToast(UI_STATE.error, apiErrorMessage(err, t('generic_error', locale)));
    },
  });

  function handleDelete(eventId: number) {
    if (!window.confirm(t('organizer_delete_confirm', locale))) return;
    deleteMutation.mutate(eventId);
  }

  const events = data?.events ?? [];

  const { data: claimsData } = useQuery({
    queryKey: [QUERY_KEYS.organizerClaims, locale],
    queryFn: () => organizerApi.get<OwnClaimsResponse>(withLocaleQuery(API.organizerClaims, locale)),
  });
  const claims = claimsData?.claims ?? [];

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <OrganizerProfileNudge locale={locale} />
        <ClaimEventPicker locale={locale} />

        {claims.length > 0 && (
          <section className={styles.claimsSection}>
            <header className={styles.claimsHeader}>
              <h2 className={styles.claimsTitle}>{t('dashboard_claims_title', locale)}</h2>
              <p className={styles.claimsSub}>{t('dashboard_claims_sub', locale)}</p>
            </header>
            <ul className={styles.claimsList}>
              {claims.map((claim) => (
                <li key={claim.id} className={styles.claimRow}>
                  <div className={styles.claimRowMain}>
                    <span className={styles.rowTitle}>
                      {claim.event_title ?? claim.publisher_name ?? t(`dashboard_claims_kind_${claim.kind}`, locale)}
                    </span>
                    <span className={styles.rowMeta}>
                      {t(`dashboard_claims_kind_${claim.kind}`, locale)}
                    </span>
                  </div>
                  <div className={styles.claimRowBadges}>
                    <span className={`${styles.claimStatusBadge} ${styles[`claimStatus_${claim.status}`] ?? ''}`}>
                      {t(`dashboard_claims_status_${claim.status}`, locale)}
                    </span>
                  </div>
                  <div className={styles.claimRowActions}>
                    {claim.status === CLAIM_STATUS_APPROVED && !claim.dormant ? (
                      <>
                        <Link to={localePath(ROUTES.organizerClaimEdit(claim.id))} className={styles.editBtn}>
                          {t('claim_edit_open_cta', locale)}
                        </Link>
                        {claim.kind === CLAIM_KIND_PUBLISHER && (
                          <Link to={localePath(ROUTES.organizerClaimEvents(claim.id))} className={styles.secondaryBtn}>
                            {t('claim_events_view_cta', locale)}
                          </Link>
                        )}
                      </>
                    ) : (
                      <Link to={localePath(ROUTES.organizerClaimPending(claim.id))} className={styles.secondaryBtn}>
                        {t('dashboard_claims_view_status_cta', locale)}
                      </Link>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        <header className={styles.masthead}>
          <h1 className={styles.heading}>{t('organizer_dashboard_title', locale)}</h1>
          <Link to={localePath(ROUTES.organizerSubmit)} className={styles.newBtn}>{t('organizer_new_event', locale)}</Link>
        </header>

        {isLoading ? (
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        ) : isError ? (
          <PageState kind={UI_STATE.error} message={t('generic_error', locale)} inline />
        ) : events.length === 0 ? (
          <EmptyState
            title={t('organizer_empty_title', locale)}
            message={t('organizer_empty_msg', locale)}
          />
        ) : (
          <ul className={styles.list}>
            {events.map((event) => (
              <li key={event.id} className={styles.row}>
                <div className={styles.rowMain}>
                  <span className={styles.rowTitle}>{event.title}</span>
                  <span className={styles.rowMeta}>{formatEventTime(event.starts_at, locale)}</span>
                </div>
                <div className={styles.rowBadges}>
                  <span className={`${styles.statusBadge} ${styles[`status_${event.status}`] ?? ''}`}>
                    {t(`organizer_status_${event.status}`, locale)}
                  </span>
                  {event.needs_review && (
                    <span className={styles.reviewBadge}>{t('organizer_needs_review', locale)}</span>
                  )}
                </div>
                <div className={styles.rowActions}>
                  <Link to={localePath(ROUTES.organizerEventEdit(event.id))} className={styles.editBtn}>
                    {t('organizer_edit', locale)}
                  </Link>
                  <button
                    type="button"
                    className={styles.deleteBtn}
                    onClick={() => handleDelete(event.id)}
                    disabled={deleteMutation.isPending}
                  >
                    {t('organizer_delete', locale)}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>

      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}
