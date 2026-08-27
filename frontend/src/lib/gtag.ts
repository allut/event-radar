import { GTAG_SCRIPT_SRC } from '../constants';
import { maskAnalyticsUrl } from '../utils';

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

/** True when this render is a Playwright/prerender pass (`navigator.webdriver`,
 * set by every WebDriver-controlled browser, including Playwright) rather than
 * a real visitor. GA4 must never load during a prerender snapshot render: it
 * would fire a fake pageview on every build and add live network activity that
 * `page.goto`'s `waitUntil: 'networkidle'` (frontend/scripts/prerender.ts) would
 * otherwise have to settle around. */
export function isPrerenderRender(): boolean {
  return typeof navigator !== 'undefined' && navigator.webdriver === true;
}

/** Builds the masked absolute URL GA4 should treat as the current page.
 * `page_path` alone is a Universal Analytics parameter GA4 ignores for
 * location purposes — GA4 instead auto-populates `page_location` from
 * `document.location.href` unless it's set explicitly, which silently
 * defeats maskAnalyticsUrl(). Every call into gtag that could report a
 * location must pass this instead of relying on `page_path`. */
function maskedPageLocation(pathname: string): string {
  return window.location.origin + maskAnalyticsUrl(pathname);
}

/** Loads gtag.js and configures GA4 with automatic pageview tracking disabled
 * (`send_page_view: false`) — pageviews are sent explicitly via trackPageview()
 * with a masked path (see maskAnalyticsUrl), so the /auth/verify magic-link
 * token or an /explore free-text search query string never reaches Google.
 * `page_location` is also set explicitly here (see maskedPageLocation) —
 * `send_page_view: false` stops the automatic pageview event, but GA4 still
 * reads the config call's `page_location` as ambient context for whatever
 * event fires next, so it needs the masked value too, not just the real one
 * left to default. `client_storage: 'none'` keeps GA4 cookieless (no
 * `_ga`/`_ga_<id>` cookie is ever set — GA4 falls back to an unpersisted
 * per-load client id instead), matching the "cookieless and aggregated"
 * claim `docs/legal/privacy.*.ts` already makes about analytics and avoiding
 * a cookie-consent-banner obligation this app has never needed. No-op with no
 * measurement ID configured (dev/preview builds don't set
 * VITE_GA_MEASUREMENT_ID), during a prerender render (see isPrerenderRender),
 * or if already initialized — guarded on `window.gtag` rather than a
 * module-level flag so React StrictMode's double-invoked effect stays
 * idempotent. */
export function initGtag(measurementId: string | undefined): void {
  if (window.gtag || !measurementId || isPrerenderRender()) return;

  window.dataLayer = window.dataLayer ?? [];
  const gtag = (...args: unknown[]) => window.dataLayer!.push(args);
  window.gtag = gtag;
  // Must be the first command: GA4's Consent Mode leaves the tag's consent
  // state permanently "unset" (Tag Assistant: "Default consent state has not
  // been set yet") until an explicit default is sent — without it, the GA4
  // tag never fires at all, not even a cookieless ping. This app collects no
  // PII and runs no ads/remarketing (Google Signals is off in the GA4
  // property), so analytics is granted and every ad-related signal denied.
  gtag('consent', 'default', {
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied',
    analytics_storage: 'granted',
  });
  gtag('js', new Date());
  gtag('set', 'client_storage', 'none');
  gtag('config', measurementId, {
    send_page_view: false,
    page_location: maskedPageLocation(window.location.pathname),
  });

  const script = document.createElement('script');
  script.async = true;
  script.src = `${GTAG_SCRIPT_SRC}?id=${measurementId}`;
  document.head.appendChild(script);
}

/** Sends one masked pageview. `path` arrives already masked (App.tsx calls
 * this with `maskAnalyticsUrl(location.pathname)`) — both `page_path` and
 * `page_location` are set from it; GA4 uses `page_location` for the actual
 * reported URL, so only setting `page_path` (a Universal Analytics
 * parameter GA4 ignores here) would leak the real, unmasked
 * `document.location.href` instead. Call once on mount and again on every
 * route change (App.tsx) — mirrors the initial automatic pageview gtag.js
 * would otherwise send unmasked via send_page_view. No-op until initGtag()
 * has run. */
export function trackPageview(path: string): void {
  window.gtag?.('event', 'page_view', {
    page_path: path,
    page_location: window.location.origin + path,
  });
}
