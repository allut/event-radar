import { useId } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { organizerApi } from '../../api/client';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { usePagedQuery } from '../../hooks/usePagedQuery';
import { usePageSettledFocus } from '../../hooks/usePageSettledFocus';
import { useNotePromotionsOffer } from '../../hooks/usePromotionsOffer';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import PromotionRowAction from '../../components/PromotionRowAction';
import PageState from '../../components/PageState';
import EmptyState from '../../components/EmptyState';
import Pager from '../../components/Pager';
import SeoTags from '../../components/SeoTags';
import { t } from '../../i18n';
import { CLAIM_EVENTS_PAGE_SIZE } from '../../_generated/sharedConstants';
import { API, PAGE_PARAM, QUERY_KEYS } from '../../constants/api';
import { UI_STATE } from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import type { PromotionRowFlags } from '../../lib/organizerPromotions';
import { formatEventTime } from '../../utils/intlFormat';
import { titleWithBrand } from '../../utils/locale';
import { withLocaleQuery, withQueryParam } from '../../utils/url';
import styles from './ClaimEvents.module.css';

interface ClaimListEvent {
  id: number;
  title: string;
  starts_at: string;
  status: string;
  /** Present only while the Promotions offer is on. */
  promotion?: PromotionRowFlags;
}

interface ClaimEventsResponse {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  events: ClaimListEvent[];
}

/** Every event a Publisher claim covers (#436) — a list view alongside the
 * single-event editor (ClaimEventEdit). Each row links into that same editor
 * page with an `event_id` query param (#437), so the editor loads/saves that
 * specific event instead of always resolving the one representative_event_
 * for_claim() picks. Paged with the shared numbered pager (spec #551): the
 * page lives in ?page, and a page change lands on the h1. */
export default function ClaimEvents() {
  const params = useParams();
  const claimId = Number(params.id);
  const [locale, handleLocaleChange] = useLocalLocale();
  const handleLogout = useOrganizerLogout();
  const { pathname } = useLocation();
  const seoMeta = useSeoMeta({
    title: titleWithBrand(t('claim_events_title', locale), locale),
    locale,
    path: pathname,
  });

  const headingId = useId();
  const { resultsHeadingRef, onPageSettled } = usePageSettledFocus();
  const {
    items: events,
    total,
    isLoading,
    isError,
    isPlaceholderData,
    pagerProps,
  } = usePagedQuery({
    queryKey: [QUERY_KEYS.organizerClaimEvents, claimId, locale],
    pageSize: CLAIM_EVENTS_PAGE_SIZE,
    fetchPage: ({ limit, offset }) =>
      organizerApi.get<ClaimEventsResponse>(
        withLocaleQuery(
          withQueryParam(
            withQueryParam(API.organizerClaimEvents(claimId), PAGE_PARAM.limit, String(limit)),
            PAGE_PARAM.offset,
            String(offset),
          ),
          locale,
        ),
      ),
    select: (data) => ({ items: data.events, total: data.total, offset: data.offset }),
    onPageSettled,
  });

  useNotePromotionsOffer(events);

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <div className={styles.eyebrow}>{t('claim_events_eyebrow', locale)}</div>
        <h1 id={headingId} ref={resultsHeadingRef} tabIndex={-1} className={styles.title}>
          {t('claim_events_title', locale)}
        </h1>
        <p className={styles.intro}>{t('claim_events_intro', locale)}</p>

        {isLoading ? (
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        ) : isError ? (
          <PageState kind={UI_STATE.error} message={t('claim_events_load_error', locale)} inline />
        ) : events.length === 0 && total > 0 ? (
          // A past-end page about to clamp to the real last page.
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        ) : events.length === 0 ? (
          <EmptyState
            title={t('claim_events_empty_title', locale)}
            message={t('claim_events_empty_msg', locale)}
          />
        ) : (
          <ul className={styles.list} aria-labelledby={headingId} aria-busy={isPlaceholderData}>
            {events.map((event) => (
              <li key={event.id} className={styles.row}>
                <div className={styles.rowMain}>
                  <span className={styles.rowTitle}>
                    <Link
                      to={`${ROUTES.organizerClaimEdit(claimId)}?event_id=${event.id}`}
                      className={styles.rowLink}
                    >
                      {event.title}
                    </Link>
                  </span>
                  <span className={styles.rowMeta}>{formatEventTime(event.starts_at, locale)}</span>
                </div>
                <span className={`${styles.statusBadge} ${styles[`status_${event.status}`] ?? ''}`}>
                  {t(`organizer_status_${event.status}`, locale)}
                </span>
                {(event.promotion?.badge || event.promotion?.promotable) && (
                  <div className={styles.rowActions}>
                    <PromotionRowAction
                      eventId={event.id}
                      eventTitle={event.title}
                      promotion={event.promotion}
                      locale={locale}
                    />
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        <Pager {...pagerProps} locale={locale} className={styles.pager} />
      </main>
    </div>
  );
}
