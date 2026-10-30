import { useEffect, useSyncExternalStore } from 'react';
import { useQuery } from '@tanstack/react-query';
import { organizerApi } from '../api/client';
import { API, QUERY_KEYS } from '../constants/api';
import { promotionsOfferHint, setPromotionsOffered, subscribePromotionsOffer } from '../lib/organizerPromotionsOffer';
import type { PromotionRowFlags } from '../lib/organizerPromotions';

/** Whether to show the Promotions nav item, from the stored offer hint. While
 * the hint is unknown (a first visit straight to Settings or Contact) it reads
 * `promotions_offer` from GET /organizer/profile, the query Settings and the
 * dashboard nudge already share, so those pages add no request. A known hint
 * costs none. */
export function usePromotionsOffer(): boolean {
  const hint = useSyncExternalStore(subscribePromotionsOffer, promotionsOfferHint, promotionsOfferHint);
  const { data } = useQuery({
    queryKey: [QUERY_KEYS.organizerProfile],
    queryFn: () => organizerApi.get<{ promotions_offer?: boolean }>(API.organizerProfile),
    enabled: hint === null,
    staleTime: Infinity,
    retry: false,
  });
  const learned = data?.promotions_offer;
  useEffect(() => {
    if (learned !== undefined) setPromotionsOffered(learned);
  }, [learned]);
  // Blocked storage keeps the hint unknown, so fall back to what the profile said.
  return hint ?? learned === true;
}

/** Learns the offer flag from a page of event rows: rows carry a `promotion`
 * key only while it is on. An empty page says nothing and leaves the hint. */
export function useNotePromotionsOffer(rows: ReadonlyArray<{ promotion?: PromotionRowFlags }>): void {
  useEffect(() => {
    if (rows.length === 0) return;
    setPromotionsOffered(rows.some((row) => row.promotion !== undefined));
  }, [rows]);
}
