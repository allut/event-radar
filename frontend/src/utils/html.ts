import DOMPurify from 'dompurify';
import {
  SAFE_URL_SCHEMES,
  SANITIZE_ALLOWED_TAGS,
  SANITIZE_ALLOWED_ATTR,
} from '../_generated/sharedConstants';

/** Defense-in-depth render guard: only allow the given URL schemes (http(s) by
 * default) into href/src attributes. The backend already drops non-http(s)
 * schemes at ingest time (safe_external_url) for scraped event data, but this
 * protects against any other path that might surface a raw URL. Callers with
 * a legitimately wider scheme set (e.g. LegalPage's first-party `mailto:`
 * links) can pass their own allowlist rather than widening the default. */
export function safeUrl(url: string | null | undefined, allowedSchemes: ReadonlySet<string> = SAFE_URL_SCHEMES): string | null {
  if (!url) return null;
  try {
    const proto = new URL(url).protocol.replace(/:$/, '');
    return allowedSchemes.has(proto) ? url : null;
  } catch {
    return null;
  }
}

// Registered once at module scope (not per sanitizeHtml call) — DOMPurify hooks
// are global, so re-adding on every call would pile up duplicate listeners.
// Forces rel="noopener noreferrer" on every sanitized <a>, matching the trusted
// outbound links in EventCard/EventDetail: without it, an anchor from
// untrusted event HTML opened via target="_blank" could use
// window.opener to navigate the origin tab (reverse tabnabbing), and omitting
// rel="noreferrer" would leak the full referrer URL to the linked site.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('rel', 'noopener noreferrer');
    node.setAttribute('target', '_blank');
  }
});

/** Client-side sanitizer for HTML from event description/important_info fields.
 * Strictly matches the backend nh3 allowlist; defense-in-depth before dangerouslySetInnerHTML. */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: SANITIZE_ALLOWED_TAGS,
    ALLOWED_ATTR: SANITIZE_ALLOWED_ATTR,
  });
}

/** Strips all HTML tags from a sanitized-but-still-HTML description field,
 * for plain-text teaser contexts (card snippets, meta descriptions) that
 * must not render markup. */
export function stripHtmlToText(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] });
}

/** True if a RichTextEditor field has real text — Tiptap's "empty" state
 * serializes as `<p></p>`, not `''`, so a plain `.trim()` on the raw HTML
 * would treat that as non-empty. */
export function hasHtmlContent(html: string): boolean {
  return stripHtmlToText(html).trim().length > 0;
}

/** Flatten an inline run (string, `{ text }` link or `{ operator }` field) to plain
 * text, for building stable React keys off authored content (react/no-array-index-key is an error). */
export function inlineText(content: ReadonlyArray<string | { text: string } | { operator: string }>): string {
  return content.map((part) => (typeof part === 'string' ? part : 'operator' in part ? part.operator : part.text)).join('');
}

/** Truncates `text` to at most `maxLength` chars for a meta/og:description,
 * cutting at the last word boundary before the limit (never mid-word) and
 * appending an ellipsis. Returns `text` unchanged when it already fits.
 * Splits on code points (Array.from), not raw UTF-16 slice(), so the cut
 * point can never land inside a surrogate pair (e.g. an emoji). */
export function truncateForMeta(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  // Walk code points only up to the cut, not the whole string.
  let cut = '';
  let count = 0;
  for (const ch of text) {
    if (count === maxLength) break;
    cut += ch;
    count += 1;
  }
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > 0 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
