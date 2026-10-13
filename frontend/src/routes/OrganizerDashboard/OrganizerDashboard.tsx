import { useId } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useLocalePath } from '../../hooks/useLocalePath';
import { usePagedQuery } from '../../hooks/usePagedQuery';
import { usePageSettledFocus } from '../../hooks/usePageSettledFocus';
import { t, ti, tn } from '../../i18n';
import { apiErrorMessage, formatCount, formatEventTime, withLocaleQuery, withQueryParam } from '../../utils';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import OrganizerProfileNudge from '../../components/OrganizerProfileNudge';
import ClaimEventPicker from '../../components/ClaimEventPicker';
import PageState from '../../components/PageState';
import EmptyState from '../../components/EmptyState';
import Pager from '../../components/Pager';
import Toast from '../../components/Toast';
import { useToast } from '../../hooks/useToast';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { API, QUERY_KEYS, PAGE_PARAM } from '../../constants/api';
import { ORGANIZER_CLAIMS_SUMMARY_KEY, ORGANIZER_CLAIMS_SUMMARY_LIMIT } from '../../constants/claims';
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
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

/** The part of GET /organizer/claims the claims summary line reads. */
interface OwnClaimsCounts {
  total: number;
  pending_count: number;
}

/** "You have N claims (M pending) → View" (spec #551): what's left of Your
 * claims on the dashboard, so a new pending claim still shows where the
 * organizer lands after signing in. Hidden until they have a claim. */
function ClaimsSummary({ locale }: { locale: string }) {
  const localePath = useLocalePath();
  const { data } = useQuery({
    queryKey: [QUERY_KEYS.organizerClaims, ORGANIZER_CLAIMS_SUMMARY_KEY],
    queryFn: () =>
      organizerApi.get<OwnClaimsCounts>(
        withQueryParam(API.organizerClaims, PAGE_PARAM.limit, String(ORGANIZER_CLAIMS_SUMMARY_LIMIT)),
      ),
  });
  if (!data || data.total === 0) return null;
  return (
    <section className={styles.summary} aria-label={t('dashboard_claims_title', locale)}>
      <p className={styles.summaryText}>
        {tn('dashboard_claims_summary', locale, data.total, { count: formatCount(data.total, locale) })}
        {data.pending_count > 0 && (
          <>
            {' ('}
            <span className={styles.summaryPending}>
              {ti('dashboard_claims_summary_pending', locale, {
                count: formatCount(data.pending_count, locale),
              })}
            </span>
            {')'}
          </>
        )}
      </p>
      <Link to={localePath(ROUTES.organizerClaims)} className={styles.summaryLink}>
        {t('dashboard_claims_summary_view', locale)}
        <span aria-hidden="true">→</span>
      </Link>
    </section>
  );
}

export default function OrganizerDashboard() {
  const [locale, handleLocaleChange] = useLocalLocale();
  const localePath = useLocalePath();
  const handleLogout = useOrganizerLogout();
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const seoMeta = useStaticSeoMeta('organizer_dashboard_title', locale);

  // Your events, paged with the shared numbered pager (spec #551): the page
  // lives in ?page, and a page change lands on the "Your events" heading.
  const eventsHeadingId = useId();
  const { resultsHeadingRef, onPageSettled } = usePageSettledFocus();
  const {
    items: events,
    total,
    isLoading,
    isError,
    isPlaceholderData,
    pagerProps,
  } = usePagedQuery({
    queryKey: [QUERY_KEYS.organizerEvents, locale],
    pageSize: ORGANIZER_EVENTS_PAGE_SIZE,
    fetchPage: ({ limit, offset }) =>
      organizerApi.get<OrganizerEventsResponse>(
        withLocaleQuery(
          withQueryParam(
            withQueryParam(API.organizerEvents, PAGE_PARAM.limit, String(limit)),
            PAGE_PARAM.offset,
            String(offset),
          ),
          locale,
        ),
      ),
    select: (data) => ({ items: data.events, total: data.total, offset: data.offset }),
    onPageSettled,
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

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <OrganizerProfileNudge locale={locale} />
        <ClaimEventPicker locale={locale} />

        <ClaimsSummary locale={locale} />

        <header className={styles.masthead}>
          <h1 id={eventsHeadingId} ref={resultsHeadingRef} tabIndex={-1} className={styles.heading}>
            {t('organizer_dashboard_title', locale)}
          </h1>
          <Link to={localePath(ROUTES.organizerSubmit)} className={styles.newBtn}>{t('organizer_new_event', locale)}</Link>
        </header>

        {isLoading ? (
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        ) : isError ? (
          <PageState kind={UI_STATE.error} message={t('generic_error', locale)} inline />
        ) : events.length === 0 && total > 0 ? (
          // A past-end page about to clamp to the real last page.
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        ) : events.length === 0 ? (
          <EmptyState
            title={t('organizer_empty_title', locale)}
            message={t('organizer_empty_msg', locale)}
          />
        ) : (
          <ul className={styles.list} aria-labelledby={eventsHeadingId} aria-busy={isPlaceholderData}>
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
        <Pager {...pagerProps} locale={locale} className={styles.pager} />
      </main>

      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}
