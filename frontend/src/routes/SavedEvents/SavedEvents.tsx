import { useMemo, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { t } from '../../i18n';
import { FIRST_KEYSET_PAGE, nextKeysetParam, withLocaleQuery } from '../../utils';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLogout } from '../../hooks/useLogout';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { useEventCardNav } from '../../hooks/useEventCardNav';
import EventCard, { type EventData } from '../../components/EventCard';
import EmptyState from '../../components/EmptyState';
import PageState from '../../components/PageState';
import TopBar from '../../components/TopBar';
import SeoTags from '../../components/SeoTags';
import SegmentedControl from '../../components/SegmentedControl';
import { API, QUERY_KEYS, PAGE_PARAM } from '../../constants/api';
import { UI_STATE } from '../../constants/core';
import {
  SAVED_TABS,
  SIGNAL_CONFIG,
  SAVED_EVENTS_PAGE_SIZE,
  type Signal,
  SIGNAL_PARAM,
} from '../../constants/feedback';
import styles from './SavedEvents.module.css';

interface SavedEventsResponse {
  events: EventData[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  next_cursor?: string | null;
}

export default function SavedEvents() {
  const nav = useEventCardNav();
  const handleLogout = useLogout();
  const { locale, handleLocaleChange, isPending: localePending } = useLocaleMutation();
  const seoMeta = useStaticSeoMeta('seo_title_saved', locale);
  const [signal, setSignal] = useState<Signal>('bookmark');

  const {
    data,
    isLoading,
    isError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: [QUERY_KEYS.saved, locale, signal],
    queryFn: ({ pageParam }) =>
      api.get<SavedEventsResponse>(
        withLocaleQuery(
          `${API.feedbackEvents}?${SIGNAL_PARAM}=${signal}&${PAGE_PARAM.limit}=${SAVED_EVENTS_PAGE_SIZE}&${PAGE_PARAM.offset}=${pageParam.offset}${pageParam.cursor ? `&${PAGE_PARAM.cursor}=${pageParam.cursor}` : ''}`,
          locale,
        ),
      ),
    initialPageParam: FIRST_KEYSET_PAGE,
    getNextPageParam: (lastPage) => nextKeysetParam(lastPage, lastPage.events.length),
    // A focus-triggered refetch of an infinite query re-requests every loaded
    // page sequentially (each re-scored server-side) — never worth it here.
    refetchOnWindowFocus: false,
  });

  const events = useMemo(() => data?.pages.flatMap((page) => page.events) ?? [], [data]);
  const tabOptions = useMemo(
    () =>
      SAVED_TABS.map((tab) => ({
        value: tab.value,
        label: `${SIGNAL_CONFIG[tab.value].icon} ${t(tab.labelKey, locale)}`,
      })),
    [locale],
  );

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} localeDisabled={localePending} />

      <main className={styles.main}>
        <header className={styles.masthead}>
          <h1 className={styles.heading}>{t('nav_saved', locale)}</h1>
        </header>

        <SegmentedControl
          options={tabOptions}
          value={signal}
          onChange={(v) => setSignal(v as Signal)}
          ariaLabel={t('nav_saved', locale)}
        />

        {isLoading ? (
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        ) : isError ? (
          <PageState kind={UI_STATE.error} message={t('saved_error', locale)} inline />
        ) : events.length === 0 ? (
          <EmptyState
            eyebrow={t('nav_saved', locale)}
            title={t('saved_empty_title', locale)}
            message={t('saved_empty_msg', locale)}
          />
        ) : (
          <div className={styles.grid}>
            {events.map((event, i) => (
              <EventCard
                key={event.id}
                event={event}
                index={i}
                locale={locale}
                nav={nav}
                variant="standard"
              />
            ))}
          </div>
        )}

        {hasNextPage && (
          <button
            type="button"
            className={styles.loadMoreBtn}
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
          >
            {t('load_more', locale)}
          </button>
        )}
      </main>
    </div>
  );
}
