import { ORGANIZER_PROMOTIONS_OFFER_KEY } from '../constants/organizer';
import { storageGet, storageSet } from './storage';

// Whether the Promotions offer flag is on, as last seen by the portal. The
// server is the authority (every /organizer/promotions route 404s while it is
// off, and event rows lose their `promotion` key); this hint only decides if
// the top bar shows the nav item, so a stale value costs one 404 page, not
// access. Stored as '1' (on) or '0' (off); a missing key means not yet known,
// which is when the top bar asks the profile endpoint. Same shape as
// lib/organizerAuth's signed-in hint.
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

export function promotionsOfferHint(): boolean | null {
  const stored = storageGet(ORGANIZER_PROMOTIONS_OFFER_KEY);
  return stored === null ? null : stored === '1';
}

export function setPromotionsOffered(offered: boolean): void {
  if (offered === promotionsOfferHint()) return;
  storageSet(ORGANIZER_PROMOTIONS_OFFER_KEY, offered ? '1' : '0');
  emit();
}
