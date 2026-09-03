import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { t } from '../../i18n';
import { withLocaleQuery } from '../../utils';
import { useAuth } from '../../hooks/useAuth';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLogout } from '../../hooks/useLogout';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
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
  QUERY_KEYS,
  SORT_DEFAULT,
  SORT_OPTIONS,
  UI_STATE,
  type DatePreset,
  type ExploreFilterType,
  type Signal,
  type SignInTrigger,
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
  const authed = useAuth();
  const handleLogout = useLogout();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseExploreFilters(searchParams), [searchParams]);
  const { locale, handleLocaleChange, isPending: localePending } = useLocaleMutation();
  const seoMeta = useStaticSeoMeta('seo_title_explore', locale);

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
    const action = signal === 'bookmark' ? 'save' : signal === 'like' ? 'thumbs_up' : 'thumbs_down';
    trackEvent(ANALYTICS_EVENTS.exploreUpsellClick, { action });
    requestSignIn(signal === 'bookmark' ? 'save' : 'thumbs');
  }, [requestSignIn]);

  const handleUpsellCtaClick = useCallback(() => {
    trackEvent(ANALYTICS_EVENTS.exploreUpsellClick, { action: 'for_you' });
    requestSignIn('for_you');
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
      trackFilterChange(EXPLORE_FILTER_TYPES.q);
      commitFilters({ ...filters, q: searchInput });
    }, EXPLORE_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput, filters]);

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
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: [QUERY_KEYS.explore, locale, filters],
    queryFn: ({ pageParam }) =>
      api.get<ExploreResponse>(
        withLocaleQuery(`/explore?${buildExploreApiQuery(filters, pageParam)}`, locale),
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.events.length : undefined,
    // A facet emptied down to zero chips means "match nothing" — skip the
    // request entirely rather than round-tripping to the backend, which
    // would treat an absent/full param as "all" and return unfiltered results.
    enabled: filters.category.length > 0 && filters.vibe.length > 0,
  });

  // filter_type is a fixed vocabulary (EXPLORE_FILTER_TYPES) — see
  // ANALYTICS_EVENTS.exploreFilterChange in constants.ts's Code Quality Rule
  // on not inlining literal event/param values at call sites.
  function trackFilterChange(filterType: ExploreFilterType) {
    trackEvent(ANALYTICS_EVENTS.exploreFilterChange, { filter_type: filterType, signed_in: authed });
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
    trackFilterChange(EXPLORE_FILTER_TYPES[kind]);
    commitFilters({ ...filters, [kind]: next, forYou });
  }

  function setDatePreset(preset: DatePreset) {
    trackFilterChange(EXPLORE_FILTER_TYPES.date);
    commitFilters({ ...filters, datePreset: preset });
  }

  function setCustomRange(from: string, to: string) {
    trackFilterChange(EXPLORE_FILTER_TYPES.date);
    commitFilters({ ...filters, datePreset: 'custom', customFrom: from, customTo: to });
  }

  function toggleFree() {
    trackFilterChange(EXPLORE_FILTER_TYPES.free);
    commitFilters({ ...filters, free: !filters.free });
  }

  function setSort(sort: SortOption) {
    trackFilterChange(EXPLORE_FILTER_TYPES.sort);
    commitFilters({ ...filters, sort });
  }

  function setForYou(next: boolean) {
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
  }

  function clearFilters() {
    setSearchInput('');
    commitFilters(DEFAULT_EXPLORE_FILTERS);
  }

  const events = useMemo(() => data?.pages.flatMap((page) => page.events) ?? [], [data]);
  // Grid render list: for anonymous visitors, the persistent upsell card is
  // spliced in as an EventCard sibling after EXPLORE_UPSELL_CARD_POSITION
  // cards (or at the end, for a shorter result set). The last event is
  // dropped to make room for it — keeping the total card count the same as
  // a signed-in grid — rather than added on top, which otherwise left one
  // orphaned card wrapping onto its own row at common viewport widths.
  type GridItem = { kind: 'event'; event: EventData; index: number } | { kind: 'upsell' };
  const gridItems = useMemo<GridItem[]>(() => {
    const visibleEvents = authed ? events : events.slice(0, Math.max(events.length - 1, 0));
    const items: GridItem[] = visibleEvents.map((event, index) => ({ kind: 'event', event, index }));
    if (!authed) {
      items.splice(Math.min(EXPLORE_UPSELL_CARD_POSITION, items.length), 0, { kind: 'upsell' });
    }
    return items;
  }, [events, authed]);
  const activeCount = activeFacetCount(filters);
  const hasActiveFilters =
    activeCount > 0 || filters.q.length > 0 || filters.forYou || filters.sort !== SORT_DEFAULT;

  const categoryOptions = useMemo(
    () => CATEGORIES.map((slug) => ({ value: slug, label: t(`category_${slug}`, locale) })),
    [locale],
  );
  const vibeOptions = useMemo(
    () => VIBES.map((slug) => ({ value: slug, label: t(`vibe_${slug}`, locale) })),
    [locale],
  );
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

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} authed={authed} localeDisabled={localePending} />

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
              value={filters.forYou ? EXPLORE_AUDIENCE_FOR_YOU : EXPLORE_AUDIENCE_ALL}
              onChange={(v) => setForYou(v === EXPLORE_AUDIENCE_FOR_YOU)}
              ariaLabel={`${t('all_events', locale)} / ${t('for_you', locale)}`}
            />
          </div>

          <div className={styles.cluster}>
            <SelectMenu
              variant="inline"
              label={t('sort_by', locale)}
              value={filters.sort}
              options={sortOptions}
              onChange={(v) => setSort(v as SortOption)}
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
