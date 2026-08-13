import { useMemo, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { t } from '../../i18n';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLogout } from '../../hooks/useLogout';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import EventCard, { type EventData } from '../../components/EventCard';
import EmptyState from '../../components/EmptyState';
import PageState from '../../components/PageState';
import TopBar from '../../components/TopBar';
import SeoTags from '../../components/SeoTags';
import SegmentedControl from '../../components/SegmentedControl';
import { SAVED_TABS, SIGNAL_CONFIG, SAVED_EVENTS_PAGE_SIZE, QUERY_KEYS, UI_STATE, type Signal } from '../../constants';
import styles from './SavedEvents.module.css';

interface SavedEventsResponse {
  events: EventData[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export default function SavedEvents() {
  const handleLogout = useLogout();
  const { locale, handleLocaleChange } = useLocaleMutation();
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
        `/feedback/events?signal=${signal}&limit=${SAVED_EVENTS_PAGE_SIZE}&offset=${pageParam}&locale=${encodeURIComponent(locale)}`,
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.events.length : undefined,
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
      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

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
            icon={SIGNAL_CONFIG[signal].icon}
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
