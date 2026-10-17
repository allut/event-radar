import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { t } from '../../i18n';
import { withLocaleQuery } from '../../utils';
import { useAuth } from '../../hooks/useAuth';
import { useEventCardNav } from '../../hooks/useEventCardNav';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLogout } from '../../hooks/useLogout';
import { usePageParam } from '../../hooks/usePageParam';
import { usePagedQuery } from '../../hooks/usePagedQuery';
import { usePageSettledFocus } from '../../hooks/usePageSettledFocus';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import { buildExploreItemListJsonLd } from '../../lib/structuredData';
import EventCard, { type EventData } from '../../components/EventCard';
import EmptyState from '../../components/EmptyState';
import PageState from '../../components/PageState';
import Pager from '../../components/Pager';
import TopBar from '../../components/TopBar';
import SeoTags from '../../components/SeoTags';
import FacetMenu from '../../components/FacetMenu';
import SegmentedControl from '../../components/SegmentedControl';
import SelectMenu from '../../components/SelectMenu';
import DateRangeMenu from '../../components/DateRangeMenu';
import SignInModal from '../../components/SignInModal';
import UpsellCard from './UpsellCard';
import { BROWSE_PAGE_SIZE, CATEGORIES, VIBES } from '../../_generated/sharedConstants';
import { API, QUERY_KEYS } from '../../constants/api';
import { UI_STATE } from '../../constants/core';
import {
  EXPLORE_AUDIENCE_ALL,
  EXPLORE_AUDIENCE_FOR_YOU,
  EXPLORE_SEARCH_DEBOUNCE_MS,
  SORT_DEFAULT,
  SORT_OPTIONS,
  SIGNAL_TO_SIGNIN_TRIGGER,
  SIGN_IN_TRIGGER_FOR_YOU,
  type DatePreset,
  type SignInTrigger,
  type SortOption,
} from '../../constants/explore';
import type { Signal } from '../../constants/feedback';
import { PRERENDER_ERROR_ATTR, PRERENDER_READY_ATTR } from '../../constants/prerender';
import { ROUTES } from '../../constants/routes';
import {
  activeFacetCount,
  buildExploreApiQuery,
  categoryOptions,
  cx,
  DEFAULT_EXPLORE_FILTERS,
  exploreFiltersToSearchParams,
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
  // Set when the relevance pool was cut at the backend ceiling; absent means false.
  total_is_lower_bound?: boolean;
}

interface CurrentUser {
  preferred_categories: string[];
  preferred_vibes: string[];
}

export default function Explore() {
  const authed = useAuth();
  const nav = useEventCardNav();
  const handleLogout = useLogout();
  const [searchParams] = useSearchParams();
  const filters = useMemo(() => parseExploreFilters(searchParams), [searchParams]);
  // Every filter/sort/search write goes through setListParams (spec #551):
  // one push that also drops ?page, so a change lands on page 1 and one
  // back press undoes it.
  const { setListParams } = usePageParam();
  // publicRoute: true — /explore joins Home/EventDetail's noRedirect SEO
  // route class (App.tsx, issue #236): its bare path always renders
  // Estonian, so the initial locale must resolve purely from the URL
  // segment, not a stored preference (see useLocaleMutation's own doc
  // comment on this gap).
  const { locale, handleLocaleChange, isPending: localePending } = useLocaleMutation({ publicRoute: true });

  // Single route-level sign-in modal (issue #235) — a second trigger click
  // while it's already open is a no-op (requestSignIn below).
  const [signInTrigger, setSignInTrigger] = useState<SignInTrigger | null>(null);

  // Stable identities (only changing when signInTrigger itself changes, not
  // on every Explore re-render) — passed down to EventCard as
  // onFeedbackBlocked, so a new reference on every keystroke in
  // the search box doesn't defeat EventCard's memo (issue #235 review).
  const requestSignIn = useCallback((trigger: SignInTrigger) => {
    // A second trigger click while the modal is already open is a no-op.
    setSignInTrigger((current) => {
      if (current !== null) return current;
      return trigger;
    });
  }, []);

  const handleFeedbackBlocked = useCallback((signal: Signal) => {
    requestSignIn(SIGNAL_TO_SIGNIN_TRIGGER[signal]);
  }, [requestSignIn]);

  const handleUpsellCtaClick = useCallback(() => {
    requestSignIn(SIGN_IN_TRIGGER_FOR_YOU);
  }, [requestSignIn]);

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
    (next: ExploreFilters) => setListParams(() => exploreFiltersToSearchParams(next)),
    [setListParams],
  );
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
  }, [searchInput, filters, commitFilters]);

  // Gated on authed — an anonymous visitor must never call this. The `api`
  // client hard-redirects to /login on any 401, which would break the
  // anonymous /explore flow if this fired signed out.
  const { data: currentUser } = useQuery({
    queryKey: [QUERY_KEYS.settings],
    queryFn: () => api.get<CurrentUser>(API.me),
    enabled: authed,
  });

  // One page per request, numbered by ?page (spec #551). Neither path holds
  // server-side state between pages: Path A orders on stable keys, but Path B
  // (For you / relevance) re-scores per request once its 30 s score cache
  // expires, and both filter on the current time, so an event can shift
  // between two page loads when the clock or its classification moves on.
  // Accepted at MVP ingestion cadence (hourly/6-hourly jobs).
  const { resultsHeadingRef, onPageSettled } = usePageSettledFocus();
  const {
    items: events,
    total,
    offset,
    isLoading,
    isError,
    isSuccess,
    isPlaceholderData,
    page,
    lastPage,
    pagerProps,
  } = usePagedQuery({
    queryKey: [QUERY_KEYS.explore, locale, filters],
    pageSize: BROWSE_PAGE_SIZE,
    fetchPage: ({ offset: pageOffset }) =>
      api.get<ExploreResponse>(
        withLocaleQuery(`${API.explore}?${buildExploreApiQuery(filters, pageOffset)}`, locale),
      ),
    select: (data) => ({
      items: data.events,
      total: data.total,
      offset: data.offset,
      totalIsLowerBound: data.total_is_lower_bound ?? false,
    }),
    onPageSettled,
    // A facet emptied down to zero chips means "match nothing" — skip the
    // request entirely rather than round-tripping to the backend, which
    // would treat an absent/full param as "all" and return unfiltered results.
    enabled: filters.category.length > 0 && filters.vibe.length > 0,
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
      commitFilters({ ...filters, [kind]: next, forYou });
    },
    [filters, currentUser, commitFilters],
  );

  const setDatePreset = useCallback(
    (preset: DatePreset) => {
      commitFilters({ ...filters, datePreset: preset });
    },
    [filters, commitFilters],
  );

  const setCustomRange = useCallback(
    (from: string, to: string) => {
      commitFilters({ ...filters, datePreset: 'custom', customFrom: from, customTo: to });
    },
    [filters, commitFilters],
  );

  const toggleFree = useCallback(() => {
    commitFilters({ ...filters, free: !filters.free });
  }, [filters, commitFilters]);

  const setSort = useCallback(
    (sort: SortOption) => {
      commitFilters({ ...filters, sort });
    },
    [filters, commitFilters],
  );

  const setForYou = useCallback(
    (next: boolean) => {
      // Anonymous visitor: turning For-you on intercepts into the sign-in
      // modal instead of applying the filter — never reaches the backend.
      if (next && !authed) {
        handleUpsellCtaClick();
        return;
      }
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
    [authed, currentUser, filters, commitFilters, handleUpsellCtaClick],
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
    // Past the last page the response is empty while total > 0: the page is
    // about to clamp, so it isn't indexable at the wrong URL for that render.
    indexable: isSuccess && !isPlaceholderData && !(events.length === 0 && total > 0),
    // Only the unfiltered default view is self-canonical per page; a
    // filtered, sorted or searched view canonicalises to /explore throughout.
    page: hasActiveFilters ? undefined : page,
  });
  // The ItemList covers the current page's events, positions 1..n.
  const jsonLd = useMemo(() => {
    if (!isSuccess) return undefined;
    return buildExploreItemListJsonLd(events, locale);
  }, [isSuccess, events, locale]);

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
      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} authed={authed} localeDisabled={localePending} showSearch={false} />

      <main className={styles.main}>
        <header className={styles.masthead}>
          <h1 className={styles.heading}>{t('nav_explore', locale)}</h1>
        </header>

        <div className={styles.toolbar}>
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
        </div>

        <section className={styles.results} aria-busy={isPlaceholderData}>
          {/* The focus target after a page change (usePageSettledFocus): the
              h1 sits above the filters, so the grid gets its own heading. */}
          <h2 ref={resultsHeadingRef} tabIndex={-1} className={styles.resultsHeading}>
            {t('explore_results_heading', locale)}
          </h2>
          {isLoading ? (
            <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
          ) : isError ? (
            <PageState kind={UI_STATE.error} message={t('explore_error', locale)} inline />
          ) : events.length === 0 && total > 0 && page !== lastPage ? (
            // A past-end page about to clamp to the real last page. On the
            // last page itself nothing clamps (a ranked total can outlive
            // events that went non-public), so it falls through to empty.
            <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
          ) : events.length === 0 ? (
            <EmptyState
              eyebrow={t('nav_explore', locale)}
              title={t('explore_empty_title', locale)}
              message={t('explore_empty_msg', locale)}
            />
          ) : (
            <div className={cx(styles.grid, isPlaceholderData && styles.gridDimmed)}>
              {!authed && <UpsellCard locale={locale} onCtaClick={handleUpsellCtaClick} />}
              {events.map((event, i) => (
                <EventCard
                  key={event.id}
                  event={event}
                  // The event's position in the whole result set, not the page.
                  index={offset + i}
                  locale={locale}
                  nav={nav}
                  variant="standard"
                  onFeedbackBlocked={authed ? undefined : handleFeedbackBlocked}
                />
              ))}
            </div>
          )}
        </section>

        {!isLoading && !isError && events.length === 0 && total === 0 && hasActiveFilters && (
          <button type="button" className={styles.clearFiltersBtn} onClick={clearFilters}>
            {t('explore_empty_clear', locale)}
          </button>
        )}

        {/* Always mounted for its live region; the rule above it only shows
            once there is a range label to separate from the grid. */}
        <Pager {...pagerProps} locale={locale} className={total > 0 ? styles.pager : undefined} />
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
