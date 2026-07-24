/** Structured legal-document content model.
 *
 * Legal prose (Privacy Policy, Terms of Service) is authored as typed,
 * first-party TS modules — not `shared/i18n` JSON — so it can carry rich
 * structure (headings, lists, inline links) and be lazy-loaded per locale
 * instead of bloating the eagerly-bundled i18nData.ts. Inline links are
 * structured data, never raw HTML, so rendering is inherently XSS-safe with no
 * dangerouslySetInnerHTML / nh3 pass needed for this first-party content.
 */

/** A run of inline content: a plain string, or a link (`text` → `href`). */
export type LegalInline = string | { text: string; href: string };

/** A block within a section: a paragraph or an unordered list. */
export type LegalBlock =
  | { kind: 'p'; content: LegalInline[] }
  | { kind: 'ul'; items: LegalInline[][] };

export interface LegalSection {
  heading: string;
  blocks: LegalBlock[];
}

export interface LegalDoc {
  title: string;
  /** ISO date, e.g. '2026-07-24'. */
  lastUpdated: string;
  /** Pre-section paragraphs shown above the first heading. */
  intro: LegalBlock[];
  sections: LegalSection[];
}
