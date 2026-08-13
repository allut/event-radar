import { LOCALE_URL_PREFIX_CODES } from '../constants';

/** Strips a leading `/en` or `/ru` locale-prefix segment from a pathname
 * (Estonian is bare, so there's nothing to strip for it), returning the bare
 * ROUTES.*-equivalent path.
 *
 * Kept in its own DOM-free module (not utils.ts, which pulls in api/client.ts
 * -> utils.ts's own `DOMPurify.addHook` module-level call) so it's safely
 * importable from plain Node build tooling — e.g. scripts/prerender.ts. */
export function stripLocalePrefix(pathname: string): string {
  const seg = pathname.split('/')[1];
  if (seg && LOCALE_URL_PREFIX_CODES.includes(seg)) {
    const rest = pathname.slice(seg.length + 1);
    return rest === '' ? '/' : rest;
  }
  return pathname;
}

/** Builds the equivalent pathname for `locale`: Estonian is bare, en/ru get a
 * `/en`/`/ru` prefix. Any existing prefix on `pathname` is stripped first, so
 * this is safe to call against either a bare or already-prefixed URL. */
export function localizedPath(pathname: string, locale: string): string {
  const bare = stripLocalePrefix(pathname);
  if (!LOCALE_URL_PREFIX_CODES.includes(locale)) return bare;
  return bare === '/' ? `/${locale}` : `/${locale}${bare}`;
}
