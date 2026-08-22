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
    expect(calls).toContainEqual(['config', 'G-TEST123', { send_page_view: false }]);
  });

  it('configures GA4 cookieless (no persistent client-id cookie)', () => {
    initGtag('G-TEST123');
    const calls = window.dataLayer as unknown[];
    expect(calls).toContainEqual(['set', 'client_storage', 'none']);
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

  it('forwards the masked path as a page_view event', () => {
    const gtag = vi.fn();
    window.gtag = gtag;
    trackPageview('/events/[id]');
    expect(gtag).toHaveBeenCalledWith('event', 'page_view', { page_path: '/events/[id]' });
  });
});
