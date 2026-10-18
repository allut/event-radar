/** Structured legal-document content model.
 *
 * Legal prose (Privacy Policy, Terms of Service) is authored as typed,
 * first-party TS modules — not `shared/i18n` JSON — so it can carry rich
 * structure (headings, lists, inline links) and be lazy-loaded per locale
 * instead of bloating the eagerly-bundled i18nData.ts. Inline links are
 * structured data, never raw HTML, so rendering is inherently XSS-safe with no
 * dangerouslySetInnerHTML / nh3 pass needed for this first-party content.
 */
import type { OperatorField } from '../../constants/operator';

/** A run of inline content: a plain string, an external link (`href`, for
 * mailto:/https: only), an internal route link (`to`, a bare ROUTES.* path with
 * an optional #hash, rendered through localePath()), or an Operator identity
 * field that shows a visible placeholder until the Operator fills it in. */
export type LegalLinkInline = string | { text: string; href: string } | { text: string; to: string };
export type LegalInline = LegalLinkInline | { operator: OperatorField };

/** Paid-slot copy only exists while the Sponsored slots flag is on (see
 * `isPromotionsSlotsEnabled()`). `slotsOn` content is dropped while it is off,
 * `slotsOff` content (the wording a slots-on variant replaces) while it is on. */
export type SlotsGate = 'slotsOn' | 'slotsOff';

/** A list item: bare inline runs, or runs carrying a gate. */
export type LegalItem = LegalInline[] | { content: LegalInline[]; gate: SlotsGate };

/** A block within a section: a paragraph, or an unordered or ordered list. */
export type LegalBlock =
  | { kind: 'p'; content: LegalInline[]; gate?: SlotsGate }
  | { kind: 'ul'; items: LegalItem[]; gate?: SlotsGate }
  | { kind: 'ol'; items: LegalItem[]; gate?: SlotsGate };

export interface LegalSection {
  /** Optional stable anchor (`/ranking#relevance`), the same in every locale. */
  id?: string;
  heading: string;
  blocks: LegalBlock[];
  gate?: SlotsGate;
}

export interface LegalDoc {
  title: string;
  /** ISO date, e.g. '2026-07-24'. */
  lastUpdated: string;
  /** Replaces `lastUpdated` while the slots flag is on, for a doc whose slots-on copy is newer. */
  lastUpdatedSlots?: string;
  /** Shows the DRAFT notice above the title (Organizer terms until legal review). */
  draft?: boolean;
  /** Pre-section paragraphs shown above the first heading. */
  intro: LegalBlock[];
  sections: LegalSection[];
}
