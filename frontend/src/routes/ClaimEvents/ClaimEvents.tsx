import { Link, useLocation, useParams } from 'react-router-dom';
import { useInfiniteQuery } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import PageState from '../../components/PageState';
import EmptyState from '../../components/EmptyState';
import SeoTags from '../../components/SeoTags';
import { t, ti } from '../../i18n';
import { API, PAGE_PARAM, QUERY_KEYS } from '../../constants/api';
import { CLAIM_EVENTS_PAGE_SIZE } from '../../constants/claims';
import { UI_STATE } from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import { formatEventTime, nextOffsetParam, titleWithBrand, withLocaleQuery } from '../../utils';
import styles from './ClaimEvents.module.css';

interface ClaimListEvent {
  id: number;
  title: string;
  starts_at: string;
  status: string;
}

interface ClaimEventsResponse {
  total: number | null;
  limit: number;
  offset: number;
  has_more: boolean;
  events: ClaimListEvent[];
}

/** Every event a Publisher claim covers (#436) — a list view alongside the
 * single-event editor (ClaimEventEdit). Each row links into that same editor
 * page with an `event_id` query param (#437), so the editor loads/saves that
 * specific event instead of always resolving the one representative_event_
 * for_claim() picks. */
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

  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: [QUERY_KEYS.organizerClaimEvents, claimId, locale],
      queryFn: ({ pageParam }) =>
        organizerApi.get<ClaimEventsResponse>(
          withLocaleQuery(
            `${API.organizerClaimEvents(claimId)}?${PAGE_PARAM.limit}=${CLAIM_EVENTS_PAGE_SIZE}&${PAGE_PARAM.offset}=${pageParam}`,
            locale,
          ),
        ),
      initialPageParam: 0,
      getNextPageParam: (lastPage) => nextOffsetParam(lastPage, lastPage.events.length),
    });

  const events = data?.pages.flatMap((page) => page.events) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <div className={styles.eyebrow}>{t('claim_events_eyebrow', locale)}</div>
        <h1 className={styles.title}>{t('claim_events_title', locale)}</h1>
        <p className={styles.intro}>{t('claim_events_intro', locale)}</p>

        {isLoading ? (
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        ) : isError ? (
          <PageState kind={UI_STATE.error} message={t('claim_events_load_error', locale)} inline />
        ) : events.length === 0 ? (
          <EmptyState
            title={t('claim_events_empty_title', locale)}
            message={t('claim_events_empty_msg', locale)}
          />
        ) : (
          <>
            <p className={styles.summary}>
              {ti('claim_events_summary', locale, { shown: String(events.length), total: String(total) })}
            </p>
            <ul className={styles.list}>
              {events.map((event) => (
                <li key={event.id}>
                  <Link
                    to={`${ROUTES.organizerClaimEdit(claimId)}?event_id=${event.id}`}
                    className={styles.row}
                  >
                    <div className={styles.rowMain}>
                      <span className={styles.rowTitle}>{event.title}</span>
                      <span className={styles.rowMeta}>{formatEventTime(event.starts_at, locale)}</span>
                    </div>
                    <span className={`${styles.statusBadge} ${styles[`status_${event.status}`] ?? ''}`}>
                      {t(`organizer_status_${event.status}`, locale)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            {hasNextPage && (
              <button
                type="button"
                className={styles.loadMore}
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
              >
                {t('load_more', locale)}
              </button>
            )}
          </>
        )}
      </main>
    </div>
  );
}
