import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import { API, QUERY_KEYS } from '../../constants/api';
import { CLAIM_SEARCH_DEBOUNCE_MS, CLAIM_SEARCH_MIN_CHARS } from '../../constants/claims';
import { ROUTES } from '../../constants/routes';
import { t, ti } from '../../i18n';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { apiErrorMessage, formatEventTime, isClaimJustificationRequiredError, withLocaleQuery, withQueryParam } from '../../utils';
import styles from './ClaimEventPicker.module.css';

interface ClaimCandidate {
  id: number;
  title: string;
  venue_name: string | null;
  starts_at: string;
  image_url: string | null;
}

interface ClaimCandidatesResponse {
  events: ClaimCandidate[];
}

interface ClaimEventPickerProps {
  locale: string;
}

/** The organizer-portal discovery surface (#414): a searchable combobox over
 * published events (mirrors VenuePicker's box/pop/option chrome — same
 * established pattern, not a new design question) plus an email-domain-
 * matched suggestions list, fetched once on mount — the dashboard *is* the
 * organizer's onboarding moment (no separate organizer onboarding route
 * exists to hang this off instead). Selecting either claims immediately and
 * lands the organizer pre-selected on #415's mechanism-specific pending
 * screen, same as the public-page ClaimPanel. */
export default function ClaimEventPicker({ locale }: ClaimEventPickerProps) {
  const queryClient = useQueryClient();
  const navigate = useLocaleNavigate();
  const rootRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [claimingId, setClaimingId] = useState<number | null>(null);
  const [claimError, setClaimError] = useState('');
  // A claim attempt that comes back needing a justification (a Piletilevi
  // listing with no specific promoter — a Series claim, #428) reveals this
  // candidate's reason field instead of erroring outright.
  const [justifyId, setJustifyId] = useState<number | null>(null);
  const [justification, setJustification] = useState('');

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query.trim()), CLAIM_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  const { data: suggestionsData } = useQuery({
    queryKey: [QUERY_KEYS.organizerClaimSuggestions, locale],
    queryFn: () =>
      organizerApi.get<ClaimCandidatesResponse>(
        withLocaleQuery(API.organizerClaimSuggestions, locale),
      ),
  });
  const suggestions = suggestionsData?.events ?? [];

  const { data: searchData } = useQuery({
    queryKey: [QUERY_KEYS.organizerClaimSearch, debouncedQuery, locale],
    queryFn: () =>
      organizerApi.get<ClaimCandidatesResponse>(
        withLocaleQuery(withQueryParam(API.organizerClaimSearch, 'q', debouncedQuery), locale),
      ),
    enabled: debouncedQuery.length >= CLAIM_SEARCH_MIN_CHARS,
  });
  const searchResults = searchData?.events ?? [];

  const claimMutation = useMutation({
    mutationFn: ({ eventId, justification }: { eventId: number; justification?: string }) =>
      organizerApi.post<{ id: number }>(API.organizerClaims, { event_id: eventId, justification }),
    onMutate: ({ eventId }) => {
      setClaimingId(eventId);
      setClaimError('');
    },
    onSuccess: (claim) => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerClaimSuggestions] });
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerEvents] });
      // Your claims and the dashboard's claims summary count the new claim.
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerClaims] });
      // Not invalidating organizerClaimSearch: navigating away unmounts this
      // popover on the same tick, so a refetch here would be wasted.
      navigate(ROUTES.organizerClaimPending(claim.id));
    },
    onError: (err, { eventId }) => {
      if (isClaimJustificationRequiredError(err)) {
        setJustifyId(eventId);
        setClaimingId(null);
        return;
      }
      setJustifyId(null);
      setClaimError(apiErrorMessage(err, t('generic_error', locale)));
      setClaimingId(null);
    },
  });

  function claim(eventId: number, withJustification?: string) {
    claimMutation.mutate({ eventId, justification: withJustification });
  }

  function renderCandidate(candidate: ClaimCandidate) {
    const awaitingJustification = justifyId === candidate.id;
    return (
      <li key={candidate.id} className={styles.option}>
        <span className={styles.optionTitle}>{candidate.title}</span>
        <span className={styles.optionMeta}>
          {candidate.venue_name ? `${candidate.venue_name} · ` : ''}
          {formatEventTime(candidate.starts_at, locale)}
        </span>
        <button
          type="button"
          className={styles.claimBtn}
          disabled={awaitingJustification || (claimMutation.isPending && claimingId === candidate.id)}
          onClick={() => claim(candidate.id)}
        >
          {claimMutation.isPending && claimingId === candidate.id
            ? t('loading', locale)
            : t('claim_strip_cta', locale)}
        </button>
        {awaitingJustification && (
          <div className={styles.justifyPanel}>
            <p className={styles.justifyMsg}>{t('claim_justification_prompt', locale)}</p>
            <textarea
              className={styles.justifyInput}
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              placeholder={t('claim_justification_placeholder', locale)}
            />
            <div className={styles.justifyActions}>
              <button
                type="button"
                className={styles.claimBtn}
                disabled={!justification.trim() || claimMutation.isPending}
                onClick={() => claim(candidate.id, justification.trim())}
              >
                {claimMutation.isPending && claimingId === candidate.id
                  ? t('loading', locale)
                  : t('claim_justification_submit', locale)}
              </button>
            </div>
          </div>
        )}
      </li>
    );
  }

  return (
    <section className={styles.wrap}>
      <h2 className={styles.heading}>{t('organizer_claim_discovery_heading', locale)}</h2>

      {suggestions.length > 0 && (
        <div className={styles.suggestions}>
          <h3 className={styles.subheading}>{t('organizer_claim_suggestions_heading', locale)}</h3>
          <ul className={styles.list}>{suggestions.map(renderCandidate)}</ul>
        </div>
      )}

      <div className={styles.box} ref={rootRef}>
        <input
          type="text"
          className={styles.input}
          value={query}
          placeholder={t('organizer_claim_search_placeholder', locale)}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          autoComplete="off"
        />
        {open && debouncedQuery.length >= CLAIM_SEARCH_MIN_CHARS && (
          <ul className={styles.pop} role="listbox">
            {searchResults.length > 0
              ? searchResults.map(renderCandidate)
              : <li className={styles.emptyOption}>{ti('organizer_claim_search_empty', locale, { query: debouncedQuery })}</li>}
          </ul>
        )}
      </div>

      {claimError && <p className={styles.error} role="alert">{claimError}</p>}
    </section>
  );
}
