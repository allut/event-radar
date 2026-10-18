// Sponsored slot (issue #603): caption, "Why?" panel and Explore placement.
// .js extensions required: Cloudflare Pages Functions import constants as unbundled ESM.

import { PROMOTION_REF_AD, PROMOTION_REF_DIGEST_AD } from '../_generated/sharedConstants.js';
import { ROUTES } from './routes.js';

// Surface variants of the "Why?" explanation (i18n keys sponsored_explain_*).
// `filters`/`none` come from the Explore response; `daily5` is the Daily 5 card.
export type SponsoredExplanation = 'filters' | 'none' | 'daily5';

export const SPONSORED_EXPLANATION_KEY: Record<SponsoredExplanation, string> = {
  filters: 'sponsored_explain_filters',
  none: 'sponsored_explain_none',
  daily5: 'sponsored_explain_daily5',
};

// Where the panel's disclosure link lands: the Ads section of the Ranking disclosure.
export const SPONSORED_RANKING_TARGET = `${ROUTES.ranking}#ads`;

// A paid link never passes link equity: the stretched card link and the ticket link.
export const SPONSORED_LINK_REL = 'sponsored';
export const SPONSORED_TICKET_REL = 'sponsored noopener noreferrer';

// Explore opt-in query param; the client omits it entirely under the prerender.
export const SPONSORED_SLOT_PARAM = 'sponsored_slot';

// Zero-based grid position of the slot on Explore page 1 (tile #4).
export const SPONSORED_EXPLORE_TILE_INDEX = 3;

// Delivery-counting marker (spec #597): ad links carry `?ref=`, the event page
// forwards a known value to the API once and strips it from the URL.
export const PROMOTION_REF_PARAM = 'ref';
export const PROMOTION_REFS: ReadonlySet<string> = new Set([PROMOTION_REF_AD, PROMOTION_REF_DIGEST_AD]);
