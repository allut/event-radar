import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ApiError, organizerApi } from '../api/client';
import { API, QUERY_KEYS } from '../constants/api';
import { setPromotionsOffered } from '../lib/organizerPromotionsOffer';
import type { OrganizerPromotionItem, OrganizerPromotionsResponse } from '../lib/organizerPromotions';

const NOT_FOUND = 404;

/** The Organizer's requests and Promotions (GET /organizer/promotions). While
 * the offer flag is off the endpoint 404s: `offered` is false then, and the
 * stored offer hint follows what the server said. */
export function useOrganizerPromotions(
  poll?: { everyMs: number; maxUpdates: number; until: (items: OrganizerPromotionItem[]) => boolean },
) {
  const query = useQuery({
    queryKey: [QUERY_KEYS.organizerPromotions],
    queryFn: () => organizerApi.get<OrganizerPromotionsResponse>(API.organizerPromotions),
    retry: false,
    refetchOnMount: 'always',
    // Polls until `until` holds or the update cap is reached.
    refetchInterval: (q) =>
      !poll || q.state.dataUpdateCount >= poll.maxUpdates || poll.until(q.state.data?.items ?? [])
        ? false
        : poll.everyMs,
  });
  const notOffered = query.error instanceof ApiError && query.error.status === NOT_FOUND;
  useEffect(() => {
    if (query.isSuccess) setPromotionsOffered(true);
    else if (notOffered) setPromotionsOffered(false);
  }, [query.isSuccess, notOffered]);
  return { ...query, notOffered, items: query.data?.items ?? [] };
}
