/** Structured FAQ content model (`/faq`).
 *
 * Same approach as `content/legal/`: first-party typed TS modules, lazy-loaded
 * per locale, with inline links as structured data (never raw HTML), so the
 * page renders without dangerouslySetInnerHTML or a sanitization pass.
 */
import type { LegalLinkInline, SlotsGate } from '../legal/types';

/** The legal inline runs. Their `to` form is an internal route link: a bare
 * ROUTES.* path (optionally with a #hash) that the page renders as a router
 * <Link> through localePath(), so /ru/faq links to /ru/privacy. `href` stays
 * for mailto:/https: only. */
export type FaqInline = LegalLinkInline;

/** A list item: bare inline runs, or runs carrying a gate. */
export type FaqItemRuns = FaqInline[] | { content: FaqInline[]; gate: SlotsGate };

export type FaqBlock =
  | { kind: 'p'; content: FaqInline[]; gate?: SlotsGate }
  | { kind: 'ul'; items: FaqItemRuns[]; gate?: SlotsGate };

export interface FaqItem {
  /** Stable English slug, the same in every locale (`/faq#is-it-free` = `/ru/faq#is-it-free`). */
  id: string;
  question: string;
  answer: FaqBlock[];
  /** Paid-slot items exist only while the slots flag is on (see SlotsGate). */
  gate?: SlotsGate;
}

export interface FaqSection {
  /** Section anchor: 'about' | 'event-goers' | 'organizers'. */
  id: string;
  heading: string;
  items: FaqItem[];
}

export interface FaqDoc {
  /** ISO date. Feeds the sitemap <lastmod>. Not shown on the page. Bump it whenever this locale's copy changes. */
  lastUpdated: string;
  /** <title> text before titleWithBrand(). */
  seoTitle: string;
  /** meta + og:description, at most 157 characters. */
  metaDescription: string;
  title: string;
  lede: string;
  /** aria-label for the section jump-nav. */
  jumpNavLabel: string;
  /** Text of the per-answer "#slug" link. */
  answerLinkLabel: string;
  sections: FaqSection[];
  contact: { heading: string; body: string; cta: string };
}
