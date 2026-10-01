/** Serializes a schema.org JSON-LD object for embedding in a
 * `<script type="application/ld+json">` body. Every "<" is escaped to
 * "<" (still valid JSON, parses back to the same value) so event-sourced
 * text (title, venue, URL) containing "</script" can never close the tag and
 * inject markup. The one serialization point shared by SeoTags (client render)
 * and scripts/prerender.ts (build-time re-save) — a plain JSON.stringify at
 * either site undoes the escape (OWASP audit #1). */
export function serializeJsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, '\\u003c');
}
