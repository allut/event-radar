import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import { API, EXPLORE_SEARCH_DEBOUNCE_MS, QUERY_KEYS } from '../../constants';
import { t, ti } from '../../i18n';
import { apiErrorMessage, formatEventTime, withQueryParam } from '../../utils';
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
  onClaimed: (status: 'pending' | 'approved') => void;
}

/** The organizer-portal discovery surface (#414): a searchable combobox over
 * published events (mirrors VenuePicker's box/pop/option chrome — same
 * established pattern, not a new design question) plus an email-domain-
 * matched suggestions list, fetched once on mount — the dashboard *is* the
 * organizer's onboarding moment (no separate organizer onboarding route
 * exists to hang this off instead). Selecting either claims immediately;
 * the claim lifecycle itself (pending/approved) is tracked from the
 * dashboard's own event list once #415's claim-editing surface exists. */
export default function ClaimEventPicker({ locale, onClaimed }: ClaimEventPickerProps) {
  const queryClient = useQueryClient();
  const rootRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [claimingId, setClaimingId] = useState<number | null>(null);
  const [claimError, setClaimError] = useState('');

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query.trim()), EXPLORE_SEARCH_DEBOUNCE_MS);
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
    queryKey: [QUERY_KEYS.organizerClaimSuggestions],
    queryFn: () => organizerApi.get<ClaimCandidatesResponse>(API.organizerClaimSuggestions),
  });
  const suggestions = suggestionsData?.events ?? [];

  const { data: searchData } = useQuery({
    queryKey: [QUERY_KEYS.organizerClaimSearch, debouncedQuery],
    queryFn: () =>
      organizerApi.get<ClaimCandidatesResponse>(
        withQueryParam(API.organizerClaimSearch, 'q', debouncedQuery),
      ),
    enabled: debouncedQuery.length >= 2,
  });
  const searchResults = searchData?.events ?? [];

  const claimMutation = useMutation({
    mutationFn: (eventId: number) =>
      organizerApi.post<{ status: 'pending' | 'approved' }>(API.organizerClaims, { event_id: eventId }),
    onMutate: (eventId) => {
      setClaimingId(eventId);
      setClaimError('');
    },
    onSuccess: (claim) => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerClaimSuggestions] });
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerEvents] });
      // Not invalidating organizerClaimSearch: query/results are cleared
      // and the popover closes on the same tick, so a refetch here would
      // just be wasted — nothing is left mounted to show it.
      setQuery('');
      setOpen(false);
      setClaimingId(null);
      onClaimed(claim.status);
    },
    onError: (err) => {
      setClaimError(apiErrorMessage(err, t('generic_error', locale)));
      setClaimingId(null);
    },
  });

  function renderCandidate(candidate: ClaimCandidate) {
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
          disabled={claimMutation.isPending && claimingId === candidate.id}
          onClick={() => claimMutation.mutate(candidate.id)}
        >
          {claimMutation.isPending && claimingId === candidate.id
            ? t('loading', locale)
            : t('claim_strip_cta', locale)}
        </button>
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
        {open && debouncedQuery.length >= 2 && (
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
