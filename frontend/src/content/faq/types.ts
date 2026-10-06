/** Structured FAQ content model (`/faq`).
 *
 * Same approach as `content/legal/`: first-party typed TS modules, lazy-loaded
 * per locale, with inline links as structured data (never raw HTML), so the
 * page renders without dangerouslySetInnerHTML or a sanitization pass.
 */
import type { LegalInline } from '../legal/types';

/** LegalInline plus an internal route link. `to` is a bare ROUTES.* path (optionally
 * with a #hash); the page renders it as a router <Link> through localePath(), so
 * /ru/faq links to /ru/privacy. LegalInline's `href` stays for mailto:/https: only. */
export type FaqInline = LegalInline | { text: string; to: string };

export type FaqBlock =
  | { kind: 'p'; content: FaqInline[] }
  | { kind: 'ul'; items: FaqInline[][] };

export interface FaqItem {
  /** Stable English slug, the same in every locale (`/faq#is-it-free` = `/ru/faq#is-it-free`). */
  id: string;
  question: string;
  answer: FaqBlock[];
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
