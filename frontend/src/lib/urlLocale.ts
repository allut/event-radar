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

/** Leading `en`/`ru` locale segment of `pathname`, or `null` when the path is
 * bare (Estonian) or the segment isn't a recognized locale. */
export function localeFromPath(pathname: string): string | null {
  const seg = pathname.split('/')[1];
  return seg && LOCALE_URL_PREFIX_CODES.includes(seg) ? seg : null;
}

/** Locale-prefixes a full `to` target (path, optionally with `?query`/`#hash`)
 * for `locale` — `localizedPath` only operates on a bare pathname, so a
 * target like `/explore?category=music` would otherwise have its query
 * string swallowed into the path-stripping logic by accident. */
export function localizedTo(to: string, locale: string): string {
  const hashIdx = to.indexOf('#');
  const hash = hashIdx === -1 ? '' : to.slice(hashIdx);
  const withoutHash = hashIdx === -1 ? to : to.slice(0, hashIdx);
  const queryIdx = withoutHash.indexOf('?');
  const pathname = queryIdx === -1 ? withoutHash : withoutHash.slice(0, queryIdx);
  const query = queryIdx === -1 ? '' : withoutHash.slice(queryIdx);
  return `${localizedPath(pathname, locale)}${query}${hash}`;
}
