import { useEffect, useSyncExternalStore } from 'react';
import { isPromotionsOffered, setPromotionsOffered, subscribePromotionsOffer } from '../lib/organizerPromotionsOffer';
import type { PromotionRowFlags } from '../lib/organizerPromotions';

/** Whether to show the Promotions nav item, from the stored offer hint. */
export function usePromotionsOffer(): boolean {
  return useSyncExternalStore(subscribePromotionsOffer, isPromotionsOffered, isPromotionsOffered);
}

/** Learns the offer flag from a page of event rows: rows carry a `promotion`
 * key only while it is on. An empty page says nothing and leaves the hint. */
export function useNotePromotionsOffer(rows: ReadonlyArray<{ promotion?: PromotionRowFlags }>): void {
  useEffect(() => {
    if (rows.length === 0) return;
    setPromotionsOffered(rows.some((row) => row.promotion !== undefined));
  }, [rows]);
}
