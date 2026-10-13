import { useCallback, useId, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { t } from '../../i18n';
import { cx, withLocaleQuery } from '../../utils';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLogout } from '../../hooks/useLogout';
import { usePageParam } from '../../hooks/usePageParam';
import { usePagedQuery } from '../../hooks/usePagedQuery';
import { usePageSettledFocus } from '../../hooks/usePageSettledFocus';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { useEventCardNav } from '../../hooks/useEventCardNav';
import EventCard, { type EventData } from '../../components/EventCard';
import EmptyState from '../../components/EmptyState';
import PageState from '../../components/PageState';
import Pager from '../../components/Pager';
import TopBar from '../../components/TopBar';
import SeoTags from '../../components/SeoTags';
import SegmentedControl from '../../components/SegmentedControl';
import { API, QUERY_KEYS, PAGE_PARAM } from '../../constants/api';
import { UI_STATE } from '../../constants/core';
import {
  SAVED_DEFAULT_SIGNAL,
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
}

const SAVED_TAB_BY_SIGNAL: Map<string, (typeof SAVED_TABS)[number]> = new Map(
  SAVED_TABS.map((tab) => [tab.value, tab]),
);
const SAVED_LIST_DEFAULTS = { [SIGNAL_PARAM]: SAVED_DEFAULT_SIGNAL };

/** The tab in `?signal`; a missing or unknown value is the default tab. */
function parseSignal(raw: string | null): Signal {
  return (raw !== null && SAVED_TAB_BY_SIGNAL.get(raw)?.value) || SAVED_DEFAULT_SIGNAL;
}

export default function SavedEvents() {
  const nav = useEventCardNav();
  const handleLogout = useLogout();
  const { locale, handleLocaleChange, isPending: localePending } = useLocaleMutation();
  const seoMeta = useStaticSeoMeta('seo_title_saved', locale);

  // The tab and the page both live in the URL (spec #551), so a refresh or a
  // shared link keeps them. A tab switch is one setListParams push: it drops
  // ?page (back to page 1) and omits the default tab.
  const [searchParams] = useSearchParams();
  const signal = parseSignal(searchParams.get(SIGNAL_PARAM));
  const { setListParams } = usePageParam({ defaults: SAVED_LIST_DEFAULTS });
  const handleTabChange = useCallback(
    (value: string) =>
      setListParams((params) => {
        params.set(SIGNAL_PARAM, value);
        return params;
      }),
    [setListParams],
  );

  // The tab buttons sit between the h1 and the grid, so a page change lands
  // on a visually hidden h2 naming the active tab, directly above the grid.
  const resultsHeadingId = useId();
  const { resultsHeadingRef, onPageSettled } = usePageSettledFocus();
  // An unsave invalidates [saved] (useFeedback), so the active page refetches:
  // the next page's first event moves up into the gap, and an emptied last
  // page clamps to the new last page.
  const {
    items: events,
    offset,
    total,
    isLoading,
    isError,
    isPlaceholderData,
    pagerProps,
  } = usePagedQuery({
    queryKey: [QUERY_KEYS.saved, locale, signal],
    pageSize: SAVED_EVENTS_PAGE_SIZE,
    fetchPage: ({ limit, offset: pageOffset }) =>
      api.get<SavedEventsResponse>(
        withLocaleQuery(
          `${API.feedbackEvents}?${SIGNAL_PARAM}=${signal}&${PAGE_PARAM.limit}=${limit}&${PAGE_PARAM.offset}=${pageOffset}`,
          locale,
        ),
      ),
    select: (data) => ({ items: data.events, total: data.total, offset: data.offset }),
    onPageSettled,
  });

  const tabOptions = useMemo(
    () =>
      SAVED_TABS.map((tab) => ({
        value: tab.value,
        label: `${SIGNAL_CONFIG[tab.value].icon} ${t(tab.labelKey, locale)}`,
      })),
    [locale],
  );
  const activeTab = SAVED_TAB_BY_SIGNAL.get(signal) ?? SAVED_TABS[0];

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
          onChange={handleTabChange}
          ariaLabel={t('nav_saved', locale)}
        />

        <section className={styles.results} aria-labelledby={resultsHeadingId} aria-busy={isPlaceholderData}>
          <h2 id={resultsHeadingId} ref={resultsHeadingRef} tabIndex={-1} className={styles.resultsHeading}>
            {t(activeTab.labelKey, locale)}
          </h2>
          {isLoading ? (
            <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
          ) : isError ? (
            <PageState kind={UI_STATE.error} message={t('saved_error', locale)} inline />
          ) : events.length === 0 && total > 0 ? (
            // A past-end page about to clamp to the real last page.
            <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
          ) : events.length === 0 ? (
            <EmptyState
              eyebrow={t('nav_saved', locale)}
              title={t('saved_empty_title', locale)}
              message={t('saved_empty_msg', locale)}
            />
          ) : (
            <div className={cx(styles.grid, isPlaceholderData && styles.dimmed)}>
              {events.map((event, i) => (
                <EventCard
                  key={event.id}
                  event={event}
                  index={offset + i}
                  locale={locale}
                  nav={nav}
                  variant="standard"
                />
              ))}
            </div>
          )}
        </section>

        <Pager {...pagerProps} locale={locale} className={total > 0 ? styles.pager : undefined} />
      </main>
    </div>
  );
}
