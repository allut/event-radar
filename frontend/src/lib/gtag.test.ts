import { describe, it, expect, beforeEach, vi } from 'vitest';
import { isPrerenderRender, initGtag, trackPageview } from './gtag';

function setWebdriver(value: boolean | undefined) {
  Object.defineProperty(navigator, 'webdriver', { value, configurable: true });
}

beforeEach(() => {
  delete (window as unknown as { gtag?: unknown }).gtag;
  delete (window as unknown as { dataLayer?: unknown }).dataLayer;
  document.head.querySelectorAll('script').forEach((el) => el.remove());
  setWebdriver(false);
});

describe('isPrerenderRender', () => {
  it('is true when navigator.webdriver is set (Playwright)', () => {
    setWebdriver(true);
    expect(isPrerenderRender()).toBe(true);
  });

  it('is false for a real browser visit', () => {
    setWebdriver(false);
    expect(isPrerenderRender()).toBe(false);
  });
});

describe('initGtag', () => {
  it('no-ops with no measurement ID', () => {
    initGtag(undefined);
    expect(window.gtag).toBeUndefined();
    expect(document.head.querySelector('script[src*="googletagmanager"]')).toBeNull();
  });

  it('no-ops during a prerender render even with a measurement ID', () => {
    setWebdriver(true);
    initGtag('G-TEST123');
    expect(window.gtag).toBeUndefined();
  });

  it('installs gtag and appends the loader script for a real visit with an ID', () => {
    initGtag('G-TEST123');
    expect(typeof window.gtag).toBe('function');
    const script = document.head.querySelector('script[src*="googletagmanager"]');
    expect(script).not.toBeNull();
    expect(script?.getAttribute('src')).toContain('G-TEST123');
  });

  it('configures GA4 with automatic pageview tracking disabled', () => {
    initGtag('G-TEST123');
    const calls = window.dataLayer as unknown[];
    expect(calls).toContainEqual([
      'config',
      'G-TEST123',
      {
        send_page_view: false,
        page_location: window.location.origin + window.location.pathname,
      },
    ]);
  });

  it('configures GA4 cookieless (no persistent client-id cookie)', () => {
    initGtag('G-TEST123');
    const calls = window.dataLayer as unknown[];
    expect(calls).toContainEqual(['set', 'client_storage', 'none']);
  });

  it('sends an explicit default consent state before config, granting analytics but denying ad signals', () => {
    // Regression: without this, GA4's Consent Mode leaves consent "unset"
    // forever and the tag never sends a hit (Tag Assistant: "Default consent
    // state has not been set yet"), even though config/event calls succeed.
    initGtag('G-TEST123');
    const calls = window.dataLayer as unknown[][];
    expect(calls).toContainEqual([
      'consent',
      'default',
      {
        ad_storage: 'denied',
        ad_user_data: 'denied',
        ad_personalization: 'denied',
        analytics_storage: 'granted',
      },
    ]);
    const consentIndex = calls.findIndex((call) => call[0] === 'consent');
    const configIndex = calls.findIndex((call) => call[0] === 'config');
    expect(consentIndex).toBeGreaterThanOrEqual(0);
    expect(consentIndex).toBeLessThan(configIndex);
  });

  it('is idempotent — a second call does not append a second script', () => {
    initGtag('G-TEST123');
    initGtag('G-TEST123');
    expect(document.head.querySelectorAll('script[src*="googletagmanager"]').length).toBe(1);
  });
});

describe('trackPageview', () => {
  it('no-ops when gtag has not been initialized', () => {
    expect(() => trackPageview('/events/1')).not.toThrow();
  });

  it('forwards the masked path as a page_view event, with a matching masked page_location', () => {
    const gtag = vi.fn();
    window.gtag = gtag;
    trackPageview('/events/[id]');
    expect(gtag).toHaveBeenCalledWith('event', 'page_view', {
      page_path: '/events/[id]',
      page_location: window.location.origin + '/events/[id]',
    });
  });

  it('sends page_location, not just page_path — GA4 ignores page_path for the reported URL', () => {
    // Regression for M-2 in the OWASP audit: GA4 auto-populates page_location
    // from the real document.location.href unless it's set explicitly, which
    // silently defeated maskAnalyticsUrl() even though page_path was masked.
    const gtag = vi.fn();
    window.gtag = gtag;
    trackPageview('/explore');
    const [, , params] = gtag.mock.calls[0] as [string, string, Record<string, unknown>];
    expect(params.page_location).toBe(window.location.origin + '/explore');
  });
});
