import { ORGANIZER_PROMOTIONS_OFFER_KEY } from '../constants/organizer';
import { storageGet, storageRemove, storageSet } from './storage';

// Whether the Promotions offer flag is on, as last seen by the portal. The
// server is the authority (every /organizer/promotions route 404s while it is
// off, and event rows lose their `promotion` key); this hint only decides if
// the top bar shows the nav item, so a stale value costs one 404 page, not
// access. Same shape as lib/organizerAuth's signed-in hint.
const listeners = new Set<() => void>();
function emit(): void {
  listeners.forEach((cb) => cb());
}
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === ORGANIZER_PROMOTIONS_OFFER_KEY) emit();
  });
}

export function subscribePromotionsOffer(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function isPromotionsOffered(): boolean {
  return storageGet(ORGANIZER_PROMOTIONS_OFFER_KEY) === '1';
}

export function setPromotionsOffered(offered: boolean): void {
  if (offered === isPromotionsOffered()) return;
  if (offered) storageSet(ORGANIZER_PROMOTIONS_OFFER_KEY, '1');
  else storageRemove(ORGANIZER_PROMOTIONS_OFFER_KEY);
  emit();
}
