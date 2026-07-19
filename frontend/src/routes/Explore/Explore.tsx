import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { t } from '../../i18n';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLogout } from '../../hooks/useLogout';
import EventCard, { type EventData } from '../../components/EventCard';
import EmptyState from '../../components/EmptyState';
import PageState from '../../components/PageState';
import TopBar from '../../components/TopBar';
import FacetMenu from '../../components/FacetMenu';
import SegmentedControl from '../../components/SegmentedControl';
import SelectMenu from '../../components/SelectMenu';
import {
  CATEGORIES,
  VIBES,
  DATE_PRESETS,
  EXPLORE_SEARCH_DEBOUNCE_MS,
  QUERY_KEYS,
  SORT_OPTIONS,
  type DatePreset,
  type SortOption,
} from '../../constants';
import {
  activeFacetCount,
  buildExploreApiQuery,
  cx,
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
  const handleLogout = useLogout();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseExploreFilters(searchParams), [searchParams]);
  const { locale, handleLocaleChange } = useLocaleMutation(['explore']);

  const [searchInput, setSearchInput] = useState(filters.q);

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
    queryKey: [QUERY_KEYS.settings],
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
    queryKey: [QUERY_KEYS.explore, filters],
    queryFn: ({ pageParam }) =>
      api.get<ExploreResponse>(`/explore?${buildExploreApiQuery(filters, pageParam)}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.events.length : undefined,
    // A facet emptied down to zero chips means "match nothing" — skip the
    // request entirely rather than round-tripping to the backend, which
    // would treat an absent/full param as "all" and return unfiltered results.
    enabled: filters.category.length > 0 && filters.vibe.length > 0,
  });

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

  function setDatePreset(preset: DatePreset) {
    commitFilters({ ...filters, datePreset: preset });
  }

  function toggleFree() {
    commitFilters({ ...filters, free: !filters.free });
  }

  function setSort(sort: SortOption) {
    commitFilters({ ...filters, sort });
  }

  function setForYou(next: boolean) {
    if (next) {
      // Fall back to "all" when the persona hasn't loaded yet (or has no
      // preference set) — avoids an accidental empty-selection/no-results
      // flash before /users/me resolves.
      const category = currentUser?.preferred_categories?.length ? currentUser.preferred_categories : [...CATEGORIES];
      const vibe = currentUser?.preferred_vibes?.length ? currentUser.preferred_vibes : [...VIBES];
      commitFilters({ ...filters, forYou: true, category, vibe });
    } else {
      commitFilters({ ...filters, forYou: false, category: [...CATEGORIES], vibe: [...VIBES] });
    }
  }

  function clearFilters() {
    setSearchInput('');
    commitFilters(DEFAULT_EXPLORE_FILTERS);
  }

  const events = useMemo(() => data?.pages.flatMap((page) => page.events) ?? [], [data]);
  const activeCount = activeFacetCount(filters);
  const hasActiveFilters =
    activeCount > 0 || filters.q.length > 0 || filters.forYou || filters.sort !== 'relevance';

  const categoryOptions = CATEGORIES.map((slug) => ({ value: slug, label: t(`category_${slug}`, locale) }));
  const vibeOptions = VIBES.map((slug) => ({ value: slug, label: t(`vibe_${slug}`, locale) }));
  const dateOptions = DATE_PRESETS.map((p) => ({ value: p.value, label: t(p.labelKey, locale) }));
  const forYouOptions = [
    { value: 'all', label: t('all_events', locale) },
    { value: 'foryou', label: t('for_you', locale) },
  ];

  return (
    <div className={styles.page}>
      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <header className={styles.masthead}>
          <h1 className={styles.heading}>{t('nav_explore', locale)}</h1>
        </header>

        <div className={styles.search}>
          <svg
            className={styles.searchIcon}
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden
          >
            <circle cx="11" cy="11" r="7" />
            <path d="M21 21l-4.3-4.3" />
          </svg>
          <input
            type="search"
            className={styles.searchInput}
            placeholder={t('explore_search_placeholder', locale)}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            aria-label={t('explore_search_placeholder', locale)}
          />
        </div>

        <div className={styles.menuRowTop}>
          <div className={styles.switchBox}>
            <SegmentedControl
              options={forYouOptions}
              value={filters.forYou ? 'foryou' : 'all'}
              onChange={(v) => setForYou(v === 'foryou')}
              ariaLabel={`${t('all_events', locale)} / ${t('for_you', locale)}`}
            />
          </div>

          <div className={styles.cluster}>
            <SelectMenu
              variant="inline"
              label={t('sort_by', locale)}
              value={filters.sort}
              options={SORT_OPTIONS.map((opt) => ({ value: opt.value, label: t(opt.labelKey, locale) }))}
              onChange={(v) => setSort(v as SortOption)}
              ariaLabel={t('sort_by', locale)}
            />
            <span className={styles.divider} aria-hidden />
            <SelectMenu
              variant="inline"
              label={t('date_prefix', locale)}
              value={filters.datePreset}
              options={dateOptions}
              onChange={(v) => setDatePreset(v as DatePreset)}
              ariaLabel={t('filter_dates', locale)}
            />
          </div>
        </div>

        <div className={styles.menuRowBottom}>
          <div className={styles.cluster}>
            <FacetMenu
              variant="inline"
              label={t('filter_categories', locale)}
              options={categoryOptions}
              selected={filters.category}
              onToggle={(v) => toggleFacet('category', v)}
              ariaLabel={t('filter_categories', locale)}
            />
            <span className={styles.divider} aria-hidden />
            <FacetMenu
              variant="inline"
              label={t('filter_vibes', locale)}
              options={vibeOptions}
              selected={filters.vibe}
              onToggle={(v) => toggleFacet('vibe', v)}
              ariaLabel={t('filter_vibes', locale)}
            />
            <span className={styles.divider} aria-hidden />
            <button
              type="button"
              className={cx(styles.freeBtn, filters.free && styles.freeBtnActive)}
              aria-pressed={filters.free}
              onClick={toggleFree}
            >
              {t('free_only', locale)}
            </button>
          </div>
        </div>

        {isLoading ? (
          <PageState kind="loading" message={t('loading', locale)} inline />
        ) : isError ? (
          <PageState kind="error" message={t('explore_error', locale)} inline />
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
    </div>
  );
}
