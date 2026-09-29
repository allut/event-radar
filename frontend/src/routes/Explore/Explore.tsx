import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { t } from '../../i18n';
import { withLocaleQuery } from '../../utils';
import { useAuth } from '../../hooks/useAuth';
import { useEventCardNav } from '../../hooks/useEventCardNav';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLogout } from '../../hooks/useLogout';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import { buildExploreItemListJsonLd } from '../../lib/structuredData';
import { trackEvent } from '../../lib/gtag';
import EventCard, { type EventData } from '../../components/EventCard';
import EmptyState from '../../components/EmptyState';
import PageState from '../../components/PageState';
import TopBar from '../../components/TopBar';
import SeoTags from '../../components/SeoTags';
import FacetMenu from '../../components/FacetMenu';
import SegmentedControl from '../../components/SegmentedControl';
import SelectMenu from '../../components/SelectMenu';
import DateRangeMenu from '../../components/DateRangeMenu';
import SignInModal from '../../components/SignInModal';
import UpsellCard from './UpsellCard';
import {
  API,
  ANALYTICS_EVENTS,
  CATEGORIES,
  VIBES,
  EXPLORE_AUDIENCE_ALL,
  EXPLORE_AUDIENCE_FOR_YOU,
  EXPLORE_FILTER_TYPES,
  EXPLORE_SEARCH_DEBOUNCE_MS,
  EXPLORE_UPSELL_CARD_POSITION,
  PRERENDER_ERROR_ATTR,
  PRERENDER_READY_ATTR,
  QUERY_KEYS,
  ROUTES,
  SORT_DEFAULT,
  SORT_OPTIONS,
  SIGNAL_TO_SIGNIN_TRIGGER,
  SIGNAL_TO_UPSELL_ACTION,
  SIGN_IN_TRIGGER_FOR_YOU,
  UI_STATE,
  UPSELL_ACTION_FOR_YOU,
  type DatePreset,
  type ExploreFilterType,
  type Signal,
  type SignInTrigger,
  type SortOption,
} from '../../constants';
import {
  activeFacetCount,
  buildExploreApiQuery,
  categoryOptions,
  cx,
  DEFAULT_EXPLORE_FILTERS,
  exploreFiltersToSearchParams,
  nextOffsetParam,
  parseExploreFilters,
  titleWithBrand,
  vibeOptions,
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
  const authed = useAuth();
  const nav = useEventCardNav();
  const handleLogout = useLogout();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseExploreFilters(searchParams), [searchParams]);
  // publicRoute: true — /explore joins Home/EventDetail's noRedirect SEO
  // route class (App.tsx, issue #236): its bare path always renders
  // Estonian, so the initial locale must resolve purely from the URL
  // segment, not a stored preference (see useLocaleMutation's own doc
  // comment on this gap).
  const { locale, handleLocaleChange, isPending: localePending } = useLocaleMutation({ publicRoute: true });

  // Single route-level sign-in modal (issue #235) — a second trigger click
  // while it's already open is a no-op (requestSignIn below).
  const [signInTrigger, setSignInTrigger] = useState<SignInTrigger | null>(null);

  useEffect(() => {
    trackEvent(ANALYTICS_EVENTS.exploreView, { signed_in: authed, locale });
    // Fired once on route landing, not on every auth/locale change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Stable identities (only changing when signInTrigger itself changes, not
  // on every Explore re-render) — passed down to EventCard as
  // onFeedbackBlocked/onCardClick, so a new reference on every keystroke in
  // the search box doesn't defeat EventCard's memo (issue #235 review).
  const requestSignIn = useCallback((trigger: SignInTrigger) => {
    // A second trigger click while the modal is already open is a no-op —
    // signin_modal_open only fires for the click that actually opens it.
    setSignInTrigger((current) => {
      if (current !== null) return current;
      trackEvent(ANALYTICS_EVENTS.signinModalOpen, { trigger });
      return trigger;
    });
  }, []);

  const handleFeedbackBlocked = useCallback((signal: Signal) => {
    trackEvent(ANALYTICS_EVENTS.exploreUpsellClick, { action: SIGNAL_TO_UPSELL_ACTION[signal] });
    requestSignIn(SIGNAL_TO_SIGNIN_TRIGGER[signal]);
  }, [requestSignIn]);

  const handleUpsellCtaClick = useCallback(() => {
    trackEvent(ANALYTICS_EVENTS.exploreUpsellClick, { action: UPSELL_ACTION_FOR_YOU });
    requestSignIn(SIGN_IN_TRIGGER_FOR_YOU);
  }, [requestSignIn]);

  const handleCardClick = useCallback((index: number) => {
    trackEvent(ANALYTICS_EVENTS.exploreCardClick, { signed_in: authed, position: index });
  }, [authed]);

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

  // Stable identities below (useCallback) — Explore re-renders on every
  // search-box keystroke (searchInput), and these are passed as onChange/
  // onToggle props to SegmentedControl/SelectMenu/FacetMenu/DateRangeMenu,
  // none of which are memo'd, so a fresh closure per render defeated any
  // future memoization (Big-O audit #5, item 3.6) — mirrors requestSignIn's
  // rationale above for EventCard.
  const commitFilters = useCallback(
    (next: ExploreFilters) => setSearchParams(exploreFiltersToSearchParams(next)),
    [setSearchParams],
  );
  // filter_type is a fixed vocabulary (EXPLORE_FILTER_TYPES) — see
  // ANALYTICS_EVENTS.exploreFilterChange in constants.ts's Code Quality Rule
  // on not inlining literal event/param values at call sites.
  const trackFilterChange = useCallback(
    (filterType: ExploreFilterType) =>
      trackEvent(ANALYTICS_EVENTS.exploreFilterChange, { filter_type: filterType, signed_in: authed }),
    [authed],
  );

  // Debounced write-through: the URL (and thus the query) only updates
  // EXPLORE_SEARCH_DEBOUNCE_MS after the user stops typing. `filters` is a
  // dependency so a chip toggle mid-debounce reschedules with the fresh
  // filter set instead of committing a stale closure over it.
  useEffect(() => {
    if (searchInput === filters.q) return;
    const handle = setTimeout(() => {
      trackFilterChange(EXPLORE_FILTER_TYPES.q);
      commitFilters({ ...filters, q: searchInput });
    }, EXPLORE_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [searchInput, filters, trackFilterChange, commitFilters]);

  // Gated on authed — an anonymous visitor must never call this. The `api`
  // client hard-redirects to /login on any 401, which would break the
  // anonymous /explore flow if this fired signed out.
  const { data: currentUser } = useQuery({
    queryKey: [QUERY_KEYS.settings],
    queryFn: () => api.get<CurrentUser>(API.me),
    enabled: authed,
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
    isSuccess,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: [QUERY_KEYS.explore, locale, filters],
    queryFn: ({ pageParam }) =>
      api.get<ExploreResponse>(
        withLocaleQuery(`${API.explore}?${buildExploreApiQuery(filters, pageParam)}`, locale),
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => nextOffsetParam(lastPage, lastPage.events.length),
    // A facet emptied down to zero chips means "match nothing" — skip the
    // request entirely rather than round-tripping to the backend, which
    // would treat an absent/full param as "all" and return unfiltered results.
    enabled: filters.category.length > 0 && filters.vibe.length > 0,
    // A focus-triggered refetch of an infinite query re-requests every loaded
    // page sequentially (each re-scored server-side) — never worth it here.
    refetchOnWindowFocus: false,
  });

  const toggleFacet = useCallback(
    (kind: 'category' | 'vibe', value: string) => {
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
      trackFilterChange(EXPLORE_FILTER_TYPES[kind]);
      commitFilters({ ...filters, [kind]: next, forYou });
    },
    [filters, currentUser, trackFilterChange, commitFilters],
  );

  const setDatePreset = useCallback(
    (preset: DatePreset) => {
      trackFilterChange(EXPLORE_FILTER_TYPES.date);
      commitFilters({ ...filters, datePreset: preset });
    },
    [filters, trackFilterChange, commitFilters],
  );

  const setCustomRange = useCallback(
    (from: string, to: string) => {
      trackFilterChange(EXPLORE_FILTER_TYPES.date);
      commitFilters({ ...filters, datePreset: 'custom', customFrom: from, customTo: to });
    },
    [filters, trackFilterChange, commitFilters],
  );

  const toggleFree = useCallback(() => {
    trackFilterChange(EXPLORE_FILTER_TYPES.free);
    commitFilters({ ...filters, free: !filters.free });
  }, [filters, trackFilterChange, commitFilters]);

  const setSort = useCallback(
    (sort: SortOption) => {
      trackFilterChange(EXPLORE_FILTER_TYPES.sort);
      commitFilters({ ...filters, sort });
    },
    [filters, trackFilterChange, commitFilters],
  );

  const setForYou = useCallback(
    (next: boolean) => {
      // Anonymous visitor: turning For-you on intercepts into the sign-in
      // modal instead of applying the filter — never reaches the backend.
      if (next && !authed) {
        handleUpsellCtaClick();
        return;
      }
      trackFilterChange(EXPLORE_FILTER_TYPES.forYou);
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
    },
    [authed, currentUser, filters, trackFilterChange, commitFilters, handleUpsellCtaClick],
  );

  const clearFilters = useCallback(() => {
    setSearchInput('');
    commitFilters(DEFAULT_EXPLORE_FILTERS);
  }, [commitFilters]);

  const handleForYouChange = useCallback(
    (v: string) => setForYou(v === EXPLORE_AUDIENCE_FOR_YOU),
    [setForYou],
  );
  const handleSortChange = useCallback((v: string) => setSort(v as SortOption), [setSort]);
  const handleCategoryToggle = useCallback((v: string) => toggleFacet('category', v), [toggleFacet]);
  const handleVibeToggle = useCallback((v: string) => toggleFacet('vibe', v), [toggleFacet]);

  const events = useMemo(() => data?.pages.flatMap((page) => page.events) ?? [], [data]);
  // Grid render list: for anonymous visitors, the persistent upsell card is
  // spliced in as an EventCard sibling after EXPLORE_UPSELL_CARD_POSITION
  // cards (or at the end, for a shorter result set). The last event is
  // dropped to make room for it — keeping the total card count the same as
  // a signed-in grid — rather than added on top, which otherwise left one
  // orphaned card wrapping onto its own row at common viewport widths.
  type GridItem = { kind: 'event'; event: EventData; index: number } | { kind: 'upsell' };
  const visibleEvents = useMemo(
    () => (authed ? events : events.slice(0, Math.max(events.length - 1, 0))),
    [events, authed],
  );
  const gridItems = useMemo<GridItem[]>(() => {
    const items: GridItem[] = visibleEvents.map((event, index) => ({ kind: 'event', event, index }));
    if (!authed) {
      items.splice(Math.min(EXPLORE_UPSELL_CARD_POSITION, items.length), 0, { kind: 'upsell' });
    }
    return items;
  }, [visibleEvents, authed]);
  const activeCount = activeFacetCount(filters);
  const hasActiveFilters =
    activeCount > 0 || filters.q.length > 0 || filters.forYou || filters.sort !== SORT_DEFAULT;

  const categoryOpts = useMemo(() => categoryOptions(locale), [locale]);
  const vibeOpts = useMemo(() => vibeOptions(locale), [locale]);
  const forYouOptions = useMemo(
    () => [
      { value: EXPLORE_AUDIENCE_ALL, label: t('all_events', locale) },
      { value: EXPLORE_AUDIENCE_FOR_YOU, label: t('for_you', locale) },
    ],
    [locale],
  );
  const sortOptions = useMemo(
    () => SORT_OPTIONS.map((opt) => ({ value: opt.value, label: t(opt.labelKey, locale) })),
    [locale],
  );

  // indexable/readiness are deliberately decoupled (issue #236): indexable
  // is derived from isSuccess alone (never true on error, per useSeoMeta's
  // own indexable contract), while the prerender readiness marker below
  // fires on isSuccess OR isError — an errored query is real, settled
  // content Playwright must stop waiting on, not something to time out over.
  const seoMeta = useSeoMeta({
    title: titleWithBrand(t('seo_title_explore', locale), locale),
    locale,
    path: ROUTES.explore,
    indexable: isSuccess,
  });
  // Crawlers only ever see the first page, so the ItemList is built from it
  // alone — not rebuilt/stringified over every page on each load-more. The
  // anonymous grid drops the last card for the upsell (see visibleEvents), which
  // only touches page 1 while it is the sole loaded page.
  const firstPage = data?.pages[0];
  const multiplePages = (data?.pages.length ?? 0) > 1;
  const jsonLd = useMemo(() => {
    if (!isSuccess || !firstPage) return undefined;
    const pageEvents = authed || multiplePages ? firstPage.events : firstPage.events.slice(0, Math.max(firstPage.events.length - 1, 0));
    return buildExploreItemListJsonLd(pageEvents, locale);
  }, [isSuccess, firstPage, authed, multiplePages, locale]);

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} jsonLd={jsonLd} />
      {/* Prerender readiness marker (issue #236) — same family as
          EventDetail.tsx's PRICE_DATA_ATTR. Set once this route's query
          settles (isSuccess or isError, never isLoading); a distinct error
          marker lets scripts/prerender.ts's snapshotTarget fail the build
          loudly instead of silently shipping a noindex page. Always
          mounted, unlike the states below it, which vary by query status. */}
      <div
        hidden
        {...(isSuccess || isError ? { [PRERENDER_READY_ATTR]: 'true' } : {})}
        {...(isError ? { [PRERENDER_ERROR_ATTR]: 'true' } : {})}
      />
      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} authed={authed} localeDisabled={localePending} />

      <main className={styles.main}>
        <header className={styles.masthead}>
          <h1 className={styles.heading}>{t('nav_explore', locale)}</h1>
        </header>

        <div className={styles.search}>
          <svg
            className={styles.searchIcon}
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
              value={filters.forYou ? EXPLORE_AUDIENCE_FOR_YOU : EXPLORE_AUDIENCE_ALL}
              onChange={handleForYouChange}
              ariaLabel={`${t('all_events', locale)} / ${t('for_you', locale)}`}
            />
          </div>

          <div className={styles.cluster}>
            <SelectMenu
              variant="inline"
              label={t('sort_by', locale)}
              value={filters.sort}
              options={sortOptions}
              onChange={handleSortChange}
              ariaLabel={t('sort_by', locale)}
            />
            <span className={styles.divider} aria-hidden />
            <DateRangeMenu
              label={t('date_prefix', locale)}
              value={filters.datePreset}
              customFrom={filters.customFrom}
              customTo={filters.customTo}
              onSelectPreset={setDatePreset}
              onChangeCustomRange={setCustomRange}
              locale={locale}
              ariaLabel={t('filter_dates', locale)}
            />
          </div>
        </div>

        <div className={styles.menuRowBottom}>
          <div className={styles.cluster}>
            <FacetMenu
              variant="inline"
              label={t('filter_categories', locale)}
              options={categoryOpts}
              selected={filters.category}
              onToggle={handleCategoryToggle}
              ariaLabel={t('filter_categories', locale)}
            />
            <span className={styles.divider} aria-hidden />
            <FacetMenu
              variant="inline"
              label={t('filter_vibes', locale)}
              options={vibeOpts}
              selected={filters.vibe}
              onToggle={handleVibeToggle}
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
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        ) : isError ? (
          <PageState kind={UI_STATE.error} message={t('explore_error', locale)} inline />
        ) : events.length === 0 ? (
          <EmptyState
            eyebrow={t('nav_explore', locale)}
            title={t('explore_empty_title', locale)}
            message={t('explore_empty_msg', locale)}
          />
        ) : (
          <div className={styles.grid}>
            {gridItems.map((item) =>
              item.kind === 'upsell' ? (
                <UpsellCard key="upsell" locale={locale} onCtaClick={handleUpsellCtaClick} />
              ) : (
                <EventCard
                  key={item.event.id}
                  event={item.event}
                  index={item.index}
                  locale={locale}
                  nav={nav}
                  variant="standard"
                  onFeedbackBlocked={authed ? undefined : handleFeedbackBlocked}
                  onCardClick={handleCardClick}
                />
              ),
            )}
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

      <SignInModal
        open={signInTrigger !== null}
        trigger={signInTrigger}
        onClose={() => setSignInTrigger(null)}
        locale={locale}
      />
    </div>
  );
}
