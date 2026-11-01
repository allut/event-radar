import { NUMERIC_ROUTE_ID_RE, GOOGLE_MAPS_SEARCH_URL } from '../constants/core';

/** A route param safe to interpolate into an API path: plain digits only, else
 * undefined (callers then leave their query disabled and render the error state). */
export function numericRouteId(raw: string | undefined): string | undefined {
  return raw !== undefined && NUMERIC_ROUTE_ID_RE.test(raw) ? raw : undefined;
}

/** Appends `key=value` to a path/query string — `?` when `path` has no query
 * string yet, `&` otherwise. `withLocaleQuery` below is this same shape,
 * fixed to the `locale` key. */
export function withQueryParam(path: string, key: string, value: string): string {
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}${key}=${encodeURIComponent(value)}`;
}

/** Appends `locale=` to a path/query string every data-fetching route sends
 * to the API — `?` when `path` has no query string yet, `&` otherwise. */
export function withLocaleQuery(path: string, locale: string): string {
  return withQueryParam(path, 'locale', locale);
}

/** True for any organizer-portal route, with or without a `/:locale` prefix
 * (e.g. `/organizer/dashboard`, `/ru/organizer/settings`) — used to pick the
 * right chrome/links (e.g. Footer's Contact link) by current portal rather
 * than by auth state alone. */
export function isOrganizerPortalPath(pathname: string): boolean {
  return /\/organizer(\/|$)/.test(pathname);
}

/** Google Maps search link: coords when present (most precise), else the
 * address, else null (no link rendered). */
export function buildMapsUrl(
  lat: number | null,
  lng: number | null,
  address: string | null,
): string | null {
  if (lat !== null && lng !== null) return `${GOOGLE_MAPS_SEARCH_URL}${lat},${lng}`;
  if (address) return `${GOOGLE_MAPS_SEARCH_URL}${encodeURIComponent(address)}`;
  return null;
}

/** Last path segment of a URL, decoded, with any query/hash stripped — used to
 * derive a displayable filename from a stored Cloudinary image URL when no
 * File object (and thus no original filename) is available, e.g. FileField's
 * edit-mode prefill. Returns '' on an unparseable URL or an empty path. */
export function fileNameFromUrl(url: string): string {
  try {
    const pathname = new URL(url).pathname;
    const last = pathname.split('/').filter(Boolean).pop() ?? '';
    return last ? decodeURIComponent(last) : '';
  } catch {
    return '';
  }
}
