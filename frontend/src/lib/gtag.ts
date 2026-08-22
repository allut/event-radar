import { GTAG_SCRIPT_SRC } from '../constants';

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

/** Loads gtag.js and configures GA4 with automatic pageview tracking disabled
 * (`send_page_view: false`) — pageviews are sent explicitly via trackPageview()
 * with a masked path (see maskAnalyticsUrl), so the /auth/verify magic-link
 * token or an /explore free-text search query string never reaches Google.
 * `client_storage: 'none'` keeps GA4 cookieless (no `_ga`/`_ga_<id>` cookie is
 * ever set — GA4 falls back to an unpersisted per-load client id instead),
 * matching the "cookieless and aggregated" claim `docs/legal/privacy.*.ts`
 * already makes about analytics and avoiding a cookie-consent-banner
 * obligation this app has never needed. No-op with no measurement ID
 * configured (dev/preview builds don't set VITE_GA_MEASUREMENT_ID), during a
 * prerender render (see isPrerenderRender), or if already initialized —
 * guarded on `window.gtag` rather than a module-level flag so React
 * StrictMode's double-invoked effect stays idempotent. */
export function initGtag(measurementId: string | undefined): void {
  if (window.gtag || !measurementId || isPrerenderRender()) return;

  window.dataLayer = window.dataLayer ?? [];
  const gtag = (...args: unknown[]) => window.dataLayer!.push(args);
  window.gtag = gtag;
  gtag('js', new Date());
  gtag('set', 'client_storage', 'none');
  gtag('config', measurementId, { send_page_view: false });

  const script = document.createElement('script');
  script.async = true;
  script.src = `${GTAG_SCRIPT_SRC}?id=${measurementId}`;
  document.head.appendChild(script);
}

/** Sends one masked-path pageview. Call once on mount and again on every route
 * change (App.tsx) — mirrors the initial automatic pageview gtag.js would
 * otherwise send unmasked via send_page_view. No-op until initGtag() has run. */
export function trackPageview(path: string): void {
  window.gtag?.('event', 'page_view', { page_path: path });
}
