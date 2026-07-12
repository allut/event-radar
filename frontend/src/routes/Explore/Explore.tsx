import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { clearToken } from '../../lib/auth';
import { t } from '../../i18n';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import EventCard, { type EventData } from '../../components/EventCard';
import EmptyState from '../../components/EmptyState';
import PageState from '../../components/PageState';
import TopBar from '../../components/TopBar';
import Chip from '../../components/Chip';
import Toggle from '../../components/Toggle';
import FilterDrawer from '../../components/FilterDrawer';
import {
  CATEGORIES,
  VIBES,
  DATE_PRESETS,
  EXPLORE_SEARCH_DEBOUNCE_MS,
  SORT_OPTIONS,
  type DatePreset,
  type SortOption,
} from '../../constants';
import {
  activeFacetCount,
  buildExploreApiQuery,
  DEFAULT_EXPLORE_FILTERS,
  exploreFiltersToSearchParams,
  parseExploreFilters,
  type ExploreFilters,
} from '../../utils';
import styles from './Explore.module.css';

interface ExploreResponse {
  events: EventData[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

interface CurrentUser {
  preferred_categories: string[];
  preferred_vibes: string[];
}

export default function Explore() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseExploreFilters(searchParams), [searchParams]);
  const { locale, handleLocaleChange } = useLocaleMutation(['explore']);

  const [searchInput, setSearchInput] = useState(filters.q);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Keep the input in sync when the URL changes from elsewhere (back/forward).
  // Adjusted during render (React's documented "Adjusting state when a prop
  // changes" pattern, state-only — no ref) rather than in an effect, so a
  // browser Back doesn't flash the stale input value for one frame.
  const [syncedUrlQ, setSyncedUrlQ] = useState(filters.q);
  if (filters.q !== syncedUrlQ) {
    setSyncedUrlQ(filters.q);
    setSearchInput(filters.q);
  }

  function commitFilters(next: ExploreFilters) {
    setSearchParams(exploreFiltersToSearchParams(next));
  }

  // Debounced write-through: the URL (and thus the query) only updates
  // EXPLORE_SEARCH_DEBOUNCE_MS after the user stops typing. `filters` is a
  // dependency so a chip toggle mid-debounce reschedules with the fresh
  // filter set instead of committing a stale closure over it.
  useEffect(() => {
    if (searchInput === filters.q) return;
    const handle = setTimeout(() => {
      commitFilters({ ...filters, q: searchInput });
    }, EXPLORE_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput, filters]);

  const { data: currentUser } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get<CurrentUser>('/users/me'),
  });

  // Each page is a fresh /explore request — the backend's Path B (For-you /
  // relevance sort) re-derives and re-scores its candidate pool per request
  // with no stable server-side cursor, so an event reclassified/published
  // between page fetches can shift rank enough to appear twice or be skipped.
  // Accepted at MVP ingestion cadence (hourly/6-hourly jobs) — same tradeoff
  // as the backend's own documented Path-B approximation (browse.py).
  const {
    data,
    isLoading,
    isError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['explore', filters],
    queryFn: ({ pageParam }) =>
      api.get<ExploreResponse>(`/explore?${buildExploreApiQuery(filters, pageParam)}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.events.length : undefined,
  });

  function handleLogout() {
    clearToken();
    queryClient.clear();
    navigate('/login', { replace: true });
  }

  function handleFeedbackSent() {
    queryClient.invalidateQueries({ queryKey: ['explore'] });
  }

  function toggleFacet(kind: 'category' | 'vibe', value: string) {
    const current = filters[kind];
    const isRemoving = current.includes(value);
    const next = isRemoving ? current.filter((v) => v !== value) : [...current, value];

    // Auto-flip: adding a facet outside the user's persona taste switches
    // For-you off (a selected-not-in-taste conflict would otherwise hide
    // every result). Removing a facet never re-enables For-you.
    let forYou = filters.forYou;
    if (forYou && !isRemoving) {
      const preferred = kind === 'category' ? currentUser?.preferred_categories : currentUser?.preferred_vibes;
      if (preferred && !preferred.includes(value)) forYou = false;
    }
    commitFilters({ ...filters, [kind]: next, forYou });
  }

  function toggleDatePreset(value: string) {
    const preset = value as DatePreset;
    commitFilters({ ...filters, datePreset: filters.datePreset === preset ? 'any' : preset });
  }

  function toggleFree() {
    commitFilters({ ...filters, free: !filters.free });
  }

  function setSort(sort: SortOption) {
    commitFilters({ ...filters, sort });
  }

  function setForYou(next: boolean) {
    commitFilters({ ...filters, forYou: next });
  }

  function clearFilters() {
    setSearchInput('');
    commitFilters(DEFAULT_EXPLORE_FILTERS);
  }

  const events = data?.pages.flatMap((page) => page.events) ?? [];
  const total = data?.pages[0]?.total ?? 0;
  const activeCount = activeFacetCount(filters);
  const hasActiveFilters =
    activeCount > 0 || filters.q.length > 0 || !filters.forYou || filters.sort !== 'relevance';

  const categoryOptions = CATEGORIES.map((slug) => ({ value: slug, label: t(`category_${slug}`, locale) }));
  const vibeOptions = VIBES.map((slug) => ({ value: slug, label: t(`vibe_${slug}`, locale) }));
  const dateOptions = DATE_PRESETS.map((p) => ({ value: p.value, label: t(p.labelKey, locale) }));

  const facetControls = (
    <>
      <Chip options={categoryOptions} selected={filters.category} onToggle={(v) => toggleFacet('category', v)} ariaLabel={t('filter_categories', locale)} />
      <Chip options={vibeOptions} selected={filters.vibe} onToggle={(v) => toggleFacet('vibe', v)} ariaLabel={t('filter_vibes', locale)} />
      <Chip options={dateOptions} selected={[filters.datePreset]} onToggle={toggleDatePreset} ariaLabel={t('filter_dates', locale)} />
      <Chip
        options={[{ value: 'free', label: t('free_only', locale) }]}
        selected={filters.free ? ['free'] : []}
        onToggle={toggleFree}
        ariaLabel={t('free_only', locale)}
      />
    </>
  );

  return (
    <div className={styles.page}>
      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <header className={styles.masthead}>
          <h1 className={styles.heading}>{t('nav_explore', locale)}</h1>
          <input
            type="search"
            className={styles.searchInput}
            placeholder={t('explore_search_placeholder', locale)}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            aria-label={t('explore_search_placeholder', locale)}
          />
        </header>

        <div className={styles.controlsRow}>
          <div className={styles.forYouControl}>
            <Toggle
              on={filters.forYou}
              onChange={setForYou}
              ariaLabel={filters.forYou ? t('for_you', locale) : t('all_events', locale)}
            />
            <span className={styles.forYouLabel}>
              {filters.forYou ? t('for_you', locale) : t('all_events', locale)}
            </span>
          </div>

          <label className={styles.sortControl}>
            <span className={styles.sortLabel}>{t('sort_by', locale)}</span>
            <select
              className={styles.sortSelect}
              value={filters.sort}
              onChange={(e) => setSort(e.target.value as SortOption)}
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{t(opt.labelKey, locale)}</option>
              ))}
            </select>
          </label>

          <button type="button" className={styles.filtersBtn} onClick={() => setDrawerOpen(true)}>
            {activeCount > 0 ? `${t('filters', locale)} (${activeCount})` : t('filters', locale)}
          </button>
        </div>

        <div className={styles.desktopFacets}>{facetControls}</div>

        {isLoading ? (
          <PageState kind="loading" message={t('loading', locale)} />
        ) : isError ? (
          <PageState kind="error" message={t('explore_error', locale)} />
        ) : events.length === 0 ? (
          <EmptyState
            icon="◉"
            title={t('explore_empty_title', locale)}
            message={t('explore_empty_msg', locale)}
          />
        ) : (
          <div className={styles.grid}>
            {events.map((event, i) => (
              <EventCard
                key={event.id}
                event={event}
                index={i}
                locale={locale}
                onFeedbackSent={handleFeedbackSent}
                variant="standard"
              />
            ))}
          </div>
        )}

        {!isLoading && !isError && events.length === 0 && hasActiveFilters && (
          <button type="button" className={styles.clearFiltersBtn} onClick={clearFilters}>
            {t('explore_empty_clear', locale)}
          </button>
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

      <FilterDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onClear={clearFilters}
        activeCount={activeCount}
        resultCount={total}
        locale={locale}
      >
        {facetControls}
      </FilterDrawer>
    </div>
  );
}
