import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { parseHTML } from 'linkedom';
import { deleteR2ObjectsByPrefix, getR2Object, putR2Object } from '../src/lib/r2ChainState';

vi.mock('../src/lib/r2ChainState', () => ({
  getR2Object: vi.fn(),
  putR2Object: vi.fn(),
  deleteR2ObjectsByPrefix: vi.fn(),
}));

import {
  buildRobotsTxt,
  buildSitemapXml,
  buildTargets,
  chainStateContentKey,
  chainStateIndexKey,
  contentReadySelector,
  createChainStatePersister,
  fetchLiveExploreCount,
  fetchResolvedTarget,
  finalizeChainState,
  finalizeSnapshotHtml,
  isAlreadyFinalized,
  isPreviewBuild,
  logZeroProgressAbort,
  main,
  parseChainStateIndex,
  partitionByChainState,
  persistChainStateTarget,
  rewriteSnapshotAssetRefs,
  sanitizeBurstIdForR2,
  selectStalenessTargets,
  selectValidationTargets,
  stripBakedThemeAttr,
} from './prerender';
import type { ChainStateIndex, PrerenderTarget, ResolvedTarget } from './prerender';
import type { RoundMarker } from '../src/lib/prerenderChain';
import faqEn from '../src/content/faq/faq.en';
import faqEt from '../src/content/faq/faq.et';
import faqRu from '../src/content/faq/faq.ru';
import { BROWSE_PAGE_SIZE, LOCALES } from '../src/_generated/sharedConstants';
import { CHAIN_STATE_PREFIX, PRERENDER_READY_SELECTOR } from '../src/constants/prerender';
import { CRAWLABLE_ICON_PATHS, PRODUCTION_ORIGIN, SITEMAP_PATH } from '../src/constants/seo';

function makeTarget(bare: string): PrerenderTarget {
  return { bare, locale: 'en' };
}

describe('contentReadySelector', () => {
  const landingSnapshot = `<html><head><link rel="canonical" href="${PRODUCTION_ORIGIN}/"></head><body></body></html>`;

  it('waits on the exact event canonical', () => {
    const sel = contentReadySelector({ bare: '/events/4107', locale: 'et', eventId: 4107 });
    expect(sel).toContain(`${PRODUCTION_ORIGIN}/events/4107`);
    const sel2 = contentReadySelector({ bare: '/events/4024', locale: 'ru', eventId: 4024 });
    expect(sel2).toContain(`${PRODUCTION_ORIGIN}/ru/events/4024`);
  });

  it('uses the locale-specific canonical for home', () => {
    expect(contentReadySelector({ bare: '/', locale: 'en' })).toContain(`${PRODUCTION_ORIGIN}/en"`);
    expect(contentReadySelector({ bare: '/', locale: 'et' })).toContain(`${PRODUCTION_ORIGIN}/"`);
  });

  it('uses PRERENDER_READY_SELECTOR for /explore', () => {
    expect(contentReadySelector({ bare: '/explore', locale: 'et' })).toBe(PRERENDER_READY_SELECTOR);
  });

  it('does not match the prerendered Landing snapshot for event or non-et home routes', () => {
    const { document } = parseHTML(landingSnapshot);
    expect(document.querySelector(contentReadySelector({ bare: '/events/4107', locale: 'et', eventId: 4107 }))).toBeNull();
    expect(document.querySelector(contentReadySelector({ bare: '/', locale: 'en' }))).toBeNull();
    expect(document.querySelector(contentReadySelector({ bare: '/', locale: 'et' }))).not.toBeNull();
  });
});

/** Unit tests (issue #89) for the zero-progress diagnostic log —
 * `logZeroProgressAbort` is the sole survivor of what used to be
 * `maybeFireDeployHook`'s branching after the redundant chain Deploy Hook
 * fire was removed (the branch push inside `commitRoundMarker` is now the
 * chain's only continuation trigger, so there is nothing left here to POST
 * or mock). */

function makeMarker(overrides: Partial<RoundMarker> = {}): RoundMarker {
  return {
    burstId: '2026-08-15T10:00:00.000Z',
    round: 3,
    status: 'continuing',
    newlyRendered: 220,
    copiedForward: 4025,
    queueRemaining: 1800,
    committedAt: '2026-08-15T10:20:00.000Z',
    ...overrides,
  };
}

describe('selectStalenessTargets', () => {
  const ev = (id: number, locale: string): PrerenderTarget => ({ bare: `/events/${id}`, locale, eventId: id }) as PrerenderTarget;

  it('picks the default-locale sibling per event when present', () => {
    const en = ev(1, 'en');
    const et = ev(1, 'et');
    const ru = ev(1, 'ru');
    expect([...selectStalenessTargets([en, et, ru])]).toEqual([et]);
  });

  it('falls back to the first validated sibling when the default locale is absent', () => {
    const en = ev(2, 'en');
    const ru = ev(2, 'ru');
    expect([...selectStalenessTargets([en, ru])]).toEqual([en]);
  });

  it('skips targets with no event id', () => {
    expect(selectStalenessTargets([makeTarget('/explore')]).size).toBe(0);
  });
});

describe('selectValidationTargets', () => {
  it('validates exactly this round\'s newly-rendered routes, excluding copied-forward routes (issue #94)', () => {
    // renderQueue is this round's candidates for (re-)rendering only —
    // copied-forward routes never enter it, so they're excluded from the
    // validation set without needing to be named here.
    const rendered = [makeTarget('/events/1'), makeTarget('/events/2')];
    const stillQueued = makeTarget('/events/3');
    const renderQueue = [...rendered, stillQueued];

    const result = selectValidationTargets(renderQueue, [stillQueued]);

    expect(result).toEqual(rendered);
  });

  it('excludes routes the render budget left queued this round', () => {
    const rendered = makeTarget('/events/1');
    const skipped = makeTarget('/events/2');

    const result = selectValidationTargets([rendered, skipped], [skipped]);

    expect(result).toEqual([rendered]);
  });

  it('validates nothing when every queued route was skipped', () => {
    const skipped = [makeTarget('/events/1'), makeTarget('/events/2')];

    const result = selectValidationTargets(skipped, skipped);

    expect(result).toEqual([]);
  });

  it('validates the whole queue when nothing was skipped', () => {
    const renderQueue = [makeTarget('/events/1'), makeTarget('/events/2')];

    const result = selectValidationTargets(renderQueue, []);

    expect(result).toEqual(renderQueue);
  });
});

describe('rewriteSnapshotAssetRefs (issue #97)', () => {
  const shellHtml =
    '<!doctype html><html><head>' +
    '<script type="module" crossorigin src="/assets/index-NEW111.js"></script>' +
    '<link rel="stylesheet" crossorigin href="/assets/index-NEW222.css">' +
    '</head><body><div id="root"></div></body></html>';

  it('replaces a stale snapshot\'s asset refs with the shell\'s current ones', () => {
    const staleHtml =
      '<!doctype html><html><head>' +
      '<title>Jazz Night</title>' +
      '<script type="module" crossorigin src="/assets/index-OLD111.js"></script>' +
      '<link rel="stylesheet" crossorigin href="/assets/index-OLD222.css">' +
      '</head><body><div id="root">rendered</div></body></html>';

    const result = rewriteSnapshotAssetRefs(staleHtml, shellHtml);

    expect(result).toContain('/assets/index-NEW111.js');
    expect(result).toContain('/assets/index-NEW222.css');
    expect(result).not.toContain('OLD111');
    expect(result).not.toContain('OLD222');
  });

  it('preserves everything else byte-for-byte — title, JSON-LD, the dateModified change marker', () => {
    const staleHtml =
      '<!doctype html><html><head>' +
      '<title>Jazz Night</title>' +
      '<script type="application/ld+json">{"@type":"Event","dateModified":"2026-08-01T00:00:00.000Z"}</script>' +
      '<script type="module" crossorigin src="/assets/index-OLD111.js"></script>' +
      '</head><body data-rh="true"><div id="root">rendered</div></body></html>';

    const result = rewriteSnapshotAssetRefs(staleHtml, shellHtml);

    expect(result).toContain('<title>Jazz Night</title>');
    expect(result).toContain('"dateModified":"2026-08-01T00:00:00.000Z"');
    expect(result).toContain('data-rh="true"');
  });

  it('appends the shell\'s asset refs when the stale snapshot has none', () => {
    const staleHtml = '<!doctype html><html><head><title>Jazz Night</title></head><body></body></html>';

    const result = rewriteSnapshotAssetRefs(staleHtml, shellHtml);

    expect(result).toContain('/assets/index-NEW111.js');
    expect(result).toContain('/assets/index-NEW222.css');
  });

  it('throws when the shell has no /assets/ references — wrong document guard', () => {
    const staleHtml = '<!doctype html><html><head></head><body></body></html>';
    const emptyShell = '<!doctype html><html><head><title>App Shell</title></head><body></body></html>';

    expect(() => rewriteSnapshotAssetRefs(staleHtml, emptyShell)).toThrow(/zero \/assets\//);
  });
});

describe('isAlreadyFinalized / finalizeSnapshotHtml fast path (#455)', () => {
  const shellHtml =
    '<!doctype html><html><head>' +
    '<script type="module" crossorigin src="/assets/index-NEW111.js"></script>' +
    '<link rel="stylesheet" crossorigin href="/assets/index-NEW222.css">' +
    '</head><body><div id="root"></div></body></html>';
  const staleHtml =
    '<!doctype html><html lang="en" data-theme="light"><head>' +
    '<title>Jazz Night</title>' +
    '<script type="application/ld+json">{"@type":"Event","dateModified":"2026-08-01T00:00:00.000Z"}</script>' +
    '<script type="module" crossorigin src="/assets/index-OLD111.js"></script>' +
    '<link rel="stylesheet" crossorigin href="/assets/index-OLD222.css">' +
    '</head><body><div id="root">rendered</div></body></html>';

  it('recognises a page a previous finalize wrote against the same shell and returns it untouched', () => {
    const finalized = finalizeSnapshotHtml(staleHtml, shellHtml);

    expect(isAlreadyFinalized(finalized, shellHtml)).toBe(true);
    expect(finalizeSnapshotHtml(finalized, shellHtml)).toBe(finalized);
  });

  it('rejects a page carrying an older build\'s asset refs', () => {
    expect(isAlreadyFinalized(staleHtml.replace(' data-theme="light"', ''), shellHtml)).toBe(false);
  });

  it('rejects a page with a baked data-theme even when its asset refs are current', () => {
    const themed = finalizeSnapshotHtml(staleHtml, shellHtml).replace('<html lang="en"', '<html lang="en" data-theme="dark"');

    expect(isAlreadyFinalized(themed, shellHtml)).toBe(false);
    expect(finalizeSnapshotHtml(themed, shellHtml)).not.toContain('data-theme');
  });

  it('rejects a page with an extra /assets/ tag the shell lacks, such as a runtime-injected modulepreload', () => {
    const finalized = finalizeSnapshotHtml(staleHtml, shellHtml);
    const extra = finalized.replace('</head>', '<link rel="modulepreload" href="/assets/RichTextEditor-X.js"></head>');

    expect(isAlreadyFinalized(extra, shellHtml)).toBe(false);
    expect(finalizeSnapshotHtml(extra, shellHtml)).not.toContain('RichTextEditor-X');
  });

  it('rejects HTML with no </head>', () => {
    expect(isAlreadyFinalized('<html><body></body></html>', shellHtml)).toBe(false);
  });
});

describe('stripBakedThemeAttr (theme-revert-on-refresh fix)', () => {
  it('removes a baked-in data-theme from the <html> element', () => {
    const html = '<!doctype html><html data-theme="light"><head><title>Jazz Night</title></head><body></body></html>';

    const result = stripBakedThemeAttr(html);

    expect(result).not.toContain('data-theme');
  });

  it('leaves other <html> attributes untouched', () => {
    const html =
      '<!doctype html><html lang="et" data-theme="dark" data-rh="lang"><head></head><body></body></html>';

    const result = stripBakedThemeAttr(html);

    expect(result).toContain('lang="et"');
    expect(result).toContain('data-rh="lang"');
    expect(result).not.toContain('data-theme');
  });

  it('is idempotent — a second call on already-stripped HTML is a no-op', () => {
    const html = '<!doctype html><html lang="et"><head></head><body></body></html>';

    const once = stripBakedThemeAttr(html);
    const twice = stripBakedThemeAttr(once);

    expect(twice).toBe(once);
  });

  it('is a no-op when there is no data-theme attribute at all', () => {
    const html = '<!doctype html><html lang="en"><head></head><body></body></html>';

    const result = stripBakedThemeAttr(html);

    expect(result).toContain('lang="en"');
    expect(result).not.toContain('data-theme');
  });
});

describe('logZeroProgressAbort', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('does not warn for a continuing round', () => {
    logZeroProgressAbort(makeMarker({ status: 'continuing', queueRemaining: 1800 }));

    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('does not warn on zero-progress when the chain-depth cap is also exceeded (routine, not a stuck-catalog alert)', () => {
    logZeroProgressAbort(
      makeMarker({ round: 11, status: 'done', newlyRendered: 0, copiedForward: 4000, queueRemaining: 900 }),
    );

    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('logs a WARNING with round/burst context on zero-progress abort', () => {
    logZeroProgressAbort(
      makeMarker({
        burstId: '2026-08-15T09:00:00.000Z',
        round: 4,
        status: 'done',
        newlyRendered: 0,
        copiedForward: 5000,
        queueRemaining: 700,
      }),
    );

    expect(warnSpy).toHaveBeenCalledTimes(1);
    const [message] = warnSpy.mock.calls[0];
    expect(message).toContain('round 4');
    expect(message).toContain('2026-08-15T09:00:00.000Z');
    expect(message).toContain('zero-progress');
  });

  it('does not warn on a natural empty-queue completion', () => {
    logZeroProgressAbort(
      makeMarker({ status: 'done', newlyRendered: 0, copiedForward: 4245, queueRemaining: 0 }),
    );

    expect(warnSpy).not.toHaveBeenCalled();
  });
});

describe('isPreviewBuild', () => {
  it('is true on Cloudflare Pages when the branch is not the production branch', () => {
    expect(
      isPreviewBuild({ CF_PAGES: '1', CF_PAGES_BRANCH: 'some-feature-branch' } as NodeJS.ProcessEnv),
    ).toBe(true);
  });

  it('is false on Cloudflare Pages for the production branch', () => {
    expect(isPreviewBuild({ CF_PAGES: '1', CF_PAGES_BRANCH: 'release' } as NodeJS.ProcessEnv)).toBe(
      false,
    );
  });

  it('is false for local/dev runs where CF_PAGES is unset', () => {
    expect(isPreviewBuild({} as NodeJS.ProcessEnv)).toBe(false);
    expect(isPreviewBuild({ CF_PAGES_BRANCH: 'some-feature-branch' } as NodeJS.ProcessEnv)).toBe(false);
  });
});

/** Google's robots.txt matching semantics (`*` wildcard, `$` end-anchor,
 * longest-match-wins, `Allow` wins ties) — mirrors
 * src/lib/seoAudit.ts's isPathAllowedByRobots, kept local since that module
 * pulls in seoValidation.ts which has no place in a scripts/ test. */
function isAllowed(robotsTxt: string, testPath: string): boolean {
  const rules: { allow: boolean; regex: RegExp; length: number }[] = [];
  let inWildcardGroup = false;
  for (const rawLine of robotsTxt.split('\n')) {
    const line = rawLine.split('#')[0].trim();
    if (!line) continue;
    const [directiveRaw, ...rest] = line.split(':');
    const directive = directiveRaw.trim().toLowerCase();
    const value = rest.join(':').trim();
    if (directive === 'user-agent') {
      inWildcardGroup = value === '*';
      continue;
    }
    if (!inWildcardGroup || (directive !== 'allow' && directive !== 'disallow')) continue;
    if (!value) continue;
    const endAnchored = value.endsWith('$');
    const body = endAnchored ? value.slice(0, -1) : value;
    const escaped = body.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
    rules.push({
      allow: directive === 'allow',
      regex: new RegExp(`^${escaped}${endAnchored ? '$' : ''}`),
      length: value.length,
    });
  }
  const matching = rules.filter((rule) => rule.regex.test(testPath));
  if (matching.length === 0) return true;
  matching.sort((a, b) => b.length - a.length || (a.allow === b.allow ? 0 : a.allow ? -1 : 1));
  return matching[0].allow;
}

describe('buildRobotsTxt', () => {
  const robotsTxt = buildRobotsTxt();

  it('allows the sitemap, the OG fallback image, and a representative built asset', () => {
    expect(isAllowed(robotsTxt, SITEMAP_PATH)).toBe(true);
    expect(isAllowed(robotsTxt, '/og-fallback.png')).toBe(true);
    expect(isAllowed(robotsTxt, '/assets/index-abc.js')).toBe(true);
  });

  it('allows every crawlable site icon path', () => {
    for (const iconPath of CRAWLABLE_ICON_PATHS) {
      expect(isAllowed(robotsTxt, iconPath)).toBe(true);
    }
  });

  it('keeps every public route allowed', () => {
    for (const path of [
      '/',
      '/en',
      '/ru',
      '/events/1',
      '/en/events/1',
      '/ru/events/1',
      '/explore',
      '/en/explore',
      '/ru/explore',
      '/faq',
      '/en/faq',
      '/ru/faq',
    ]) {
      expect(isAllowed(robotsTxt, path)).toBe(true);
    }
  });

  it('keeps a filtered /explore query string crawlable — not $-anchored (issue #236)', () => {
    for (const path of ['/explore?category=music', '/en/explore?vibe=chill&free=true']) {
      expect(isAllowed(robotsTxt, path)).toBe(true);
    }
  });

  it('allows the three FAQ routes without a $ anchor', () => {
    const lines = robotsTxt.split('\n');
    for (const line of ['Allow: /faq', 'Allow: /en/faq', 'Allow: /ru/faq']) {
      expect(lines).toContain(line);
    }
    expect(isAllowed(robotsTxt, '/en/faq#is-it-free')).toBe(true);
  });

  it('keeps an authenticated route blocked — proves the inverse-allowlist is intact', () => {
    expect(isAllowed(robotsTxt, '/settings')).toBe(false);
  });

  it('allows the URL named in its own Sitemap: directive', () => {
    const sitemapDirective = robotsTxt.split('\n').find((line) => line.startsWith('Sitemap:'));
    expect(sitemapDirective).toBeDefined();
    const sitemapUrl = new URL(sitemapDirective!.replace('Sitemap:', '').trim());
    expect(isAllowed(robotsTxt, sitemapUrl.pathname)).toBe(true);
  });
});

describe('buildTargets', () => {
  it('puts the FAQ right after explore in every locale, before event targets', () => {
    const targets = buildTargets([{ id: 7, updatedAt: '2026-10-01T00:00:00Z' }]);
    for (const { code } of LOCALES) {
      const bares = targets.filter((t) => t.locale === code).map((t) => t.bare);
      expect(bares).toEqual(['/', '/explore', '/faq', '/events/7']);
    }
  });

  it('keeps home as the very first target', () => {
    expect(buildTargets([])[0].bare).toBe('/');
  });

  it('carries no event id or change marker on the FAQ target', () => {
    const faq = buildTargets([]).find((t) => t.bare === '/faq')!;
    expect(faq.eventId).toBeUndefined();
    expect(faq.updatedAt).toBeUndefined();
  });
});

describe('buildSitemapXml', () => {
  const buildTimestamp = '2026-10-07T06:00:00.000Z';
  const { document } = parseHTML(buildSitemapXml(buildTargets([]), buildTimestamp));
  const urls = [...document.querySelectorAll('url')].map((url) => ({
    loc: url.querySelector('loc')!.textContent,
    lastmod: url.querySelector('lastmod')!.textContent,
  }));

  it("uses each locale's FaqDoc.lastUpdated as the FAQ <lastmod>, not the build time", () => {
    expect(urls).toContainEqual({ loc: `${PRODUCTION_ORIGIN}/faq`, lastmod: faqEt.lastUpdated });
    expect(urls).toContainEqual({ loc: `${PRODUCTION_ORIGIN}/en/faq`, lastmod: faqEn.lastUpdated });
    expect(urls).toContainEqual({ loc: `${PRODUCTION_ORIGIN}/ru/faq`, lastmod: faqRu.lastUpdated });
  });

  it('lists each FAQ URL right after its locale explore URL', () => {
    const locs = urls.map((u) => u.loc);
    for (const prefix of ['', '/en', '/ru']) {
      expect(locs.indexOf(`${PRODUCTION_ORIGIN}${prefix}/faq`)).toBe(
        locs.indexOf(`${PRODUCTION_ORIGIN}${prefix}/explore`) + 1,
      );
    }
  });

  it('keeps the build timestamp on home, the first <lastmod>', () => {
    expect(urls[0]).toEqual({ loc: `${PRODUCTION_ORIGIN}/`, lastmod: buildTimestamp });
  });
});

describe('fetchLiveExploreCount (issue #236)', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function mockExploreTotal(total: number): void {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ total }),
    } as Response);
  }

  it('subtracts one, matching the anonymous view\'s upsell-card truncation — a 3-event catalog resolves to 2', async () => {
    mockExploreTotal(3);
    await expect(fetchLiveExploreCount('en')).resolves.toBe(2);
  });

  it('floors at 0 rather than going negative for an empty catalog', async () => {
    mockExploreTotal(0);
    await expect(fetchLiveExploreCount('en')).resolves.toBe(0);
  });

  it('caps at BROWSE_PAGE_SIZE before subtracting, mirroring events.length only ever reflecting the first page', async () => {
    mockExploreTotal(BROWSE_PAGE_SIZE + 50);
    await expect(fetchLiveExploreCount('en')).resolves.toBe(BROWSE_PAGE_SIZE - 1);
  });

  it('returns undefined on a non-ok response rather than throwing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: false } as Response);
    await expect(fetchLiveExploreCount('en')).resolves.toBeUndefined();
  });

  it('returns undefined on a network failure rather than throwing', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network'));
    await expect(fetchLiveExploreCount('en')).resolves.toBeUndefined();
  });
});

describe('main — Preview short-circuit (issue #95)', () => {
  let logSpy: ReturnType<typeof vi.spyOn>;
  let fetchSpy: ReturnType<typeof vi.spyOn>;
  const originalCfPages = process.env.CF_PAGES;
  const originalCfPagesBranch = process.env.CF_PAGES_BRANCH;

  beforeEach(() => {
    logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      throw new Error('fetch must not be called on a Preview build');
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    for (const [key, original] of [
      ['CF_PAGES', originalCfPages],
      ['CF_PAGES_BRANCH', originalCfPagesBranch],
    ] as const) {
      if (original === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = original;
      }
    }
  });

  it('exits before any rendering, sitemap/robots, validation, or fetch work on a non-production Cloudflare Pages branch', async () => {
    process.env.CF_PAGES = '1';
    process.env.CF_PAGES_BRANCH = 'some-feature-branch';

    await expect(main()).resolves.toBeUndefined();

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(logSpy).toHaveBeenCalledWith(expect.stringContaining('skipping prerender pass'));
  });
});

describe('chain-state manifest write path (issue #367)', () => {
  const putR2ObjectMock = vi.mocked(putR2Object);
  const deleteR2ObjectsByPrefixMock = vi.mocked(deleteR2ObjectsByPrefix);

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('sanitizeBurstIdForR2', () => {
    it('replaces colons and dots so an ISO burstId is a valid R2 key segment', () => {
      expect(sanitizeBurstIdForR2('2026-08-15T10:00:00.000Z')).toBe('2026-08-15T10-00-00-000Z');
    });
  });

  describe('chainStateContentKey / chainStateIndexKey', () => {
    it('builds the target content key under the sanitized burst prefix', () => {
      expect(chainStateContentKey('2026-08-15T10-00-00-000Z', 'en', 42)).toBe(
        `${CHAIN_STATE_PREFIX}2026-08-15T10-00-00-000Z/targets/en-42.html`,
      );
    });

    it('builds the index key under the sanitized burst prefix', () => {
      expect(chainStateIndexKey('2026-08-15T10-00-00-000Z')).toBe(
        `${CHAIN_STATE_PREFIX}2026-08-15T10-00-00-000Z/index.json`,
      );
    });
  });

  describe('parseChainStateIndex', () => {
    it('returns an empty index when no manifest exists yet (null read)', () => {
      expect(parseChainStateIndex(null)).toEqual({});
    });

    it('returns an empty index and logs rather than throwing on malformed JSON', () => {
      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      expect(parseChainStateIndex('not json')).toEqual({});

      expect(errorSpy).toHaveBeenCalled();
      errorSpy.mockRestore();
    });

    it('round-trips a previously-written index', () => {
      const index: ChainStateIndex = { 'en:42': { resolvedAtRound: 2 } };

      expect(parseChainStateIndex(JSON.stringify(index))).toEqual(index);
    });

    it('returns an empty index and logs rather than trusting a JSON array as the manifest shape', () => {
      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      expect(parseChainStateIndex(JSON.stringify(['not', 'a', 'map']))).toEqual({});

      expect(errorSpy).toHaveBeenCalled();
      errorSpy.mockRestore();
    });
  });

  describe('persistChainStateTarget — shared by the copy-forward and successful-render resolution points', () => {
    it('PUTs the finalized HTML and records the index entry for an event target (copy-forward resolution point)', async () => {
      putR2ObjectMock.mockResolvedValue(true);
      const index: ChainStateIndex = {};
      const target: PrerenderTarget = { bare: '/events/42', locale: 'en', eventId: 42 };

      await persistChainStateTarget('burst-1', 3, target, '<html>copied-forward</html>', index);

      expect(putR2ObjectMock).toHaveBeenCalledWith(
        `${CHAIN_STATE_PREFIX}burst-1/targets/en-42.html`,
        '<html>copied-forward</html>',
        'text/html',
      );
      expect(index).toEqual({ 'en:42': { resolvedAtRound: 3 } });
    });

    it('PUTs the finalized HTML and records the index entry for an event target (successful-render resolution point)', async () => {
      putR2ObjectMock.mockResolvedValue(true);
      const index: ChainStateIndex = {};
      const target: PrerenderTarget = { bare: '/events/7', locale: 'ru', eventId: 7 };

      await persistChainStateTarget('burst-1', 1, target, '<html>freshly-rendered</html>', index);

      expect(putR2ObjectMock).toHaveBeenCalledWith(
        `${CHAIN_STATE_PREFIX}burst-1/targets/ru-7.html`,
        '<html>freshly-rendered</html>',
        'text/html',
      );
      expect(index).toEqual({ 'ru:7': { resolvedAtRound: 1 } });
    });

    it('never writes a manifest entry for a home/explore target (no eventId)', async () => {
      const index: ChainStateIndex = {};
      const target: PrerenderTarget = { bare: '/explore', locale: 'en' };

      await persistChainStateTarget('burst-1', 1, target, '<html>explore</html>', index);

      expect(putR2ObjectMock).not.toHaveBeenCalled();
      expect(index).toEqual({});
    });

    it('never records an index entry when the content PUT fails, so the manifest cannot claim a target is resolved with no matching object in the bucket', async () => {
      putR2ObjectMock.mockResolvedValue(false);
      const index: ChainStateIndex = {};
      const target: PrerenderTarget = { bare: '/events/9', locale: 'en', eventId: 9 };

      await persistChainStateTarget('burst-1', 1, target, '<html>unwritten</html>', index);

      expect(putR2ObjectMock).toHaveBeenCalled();
      expect(index).toEqual({});
    });
  });

  describe('finalizeChainState — end-of-round manifest write', () => {
    it('PUTs the accumulated index exactly once when the round is continuing', async () => {
      putR2ObjectMock.mockResolvedValue(true);
      const index: ChainStateIndex = { 'en:1': { resolvedAtRound: 2 } };

      await finalizeChainState('burst-1', index, true);

      expect(putR2ObjectMock).toHaveBeenCalledTimes(1);
      expect(putR2ObjectMock).toHaveBeenCalledWith(
        `${CHAIN_STATE_PREFIX}burst-1/index.json`,
        JSON.stringify(index),
        'application/json',
      );
      expect(deleteR2ObjectsByPrefixMock).not.toHaveBeenCalled();
    });

    it('deletes the whole burst prefix instead of writing the index when the round is done', async () => {
      deleteR2ObjectsByPrefixMock.mockResolvedValue(true);
      const index: ChainStateIndex = { 'en:1': { resolvedAtRound: 2 } };

      await finalizeChainState('burst-1', index, false);

      expect(deleteR2ObjectsByPrefixMock).toHaveBeenCalledWith(`${CHAIN_STATE_PREFIX}burst-1/`);
      expect(putR2ObjectMock).not.toHaveBeenCalled();
    });

    it('never throws when the underlying R2 operation fails open (fail-open fallback)', async () => {
      putR2ObjectMock.mockResolvedValue(false);
      deleteR2ObjectsByPrefixMock.mockResolvedValue(false);

      await expect(finalizeChainState('burst-1', {}, true)).resolves.toBeUndefined();
      await expect(finalizeChainState('burst-1', {}, false)).resolves.toBeUndefined();
    });
  });
});

describe('createChainStatePersister — deferred chain-state PUTs (issue #537)', () => {
  const event = (eventId: number): PrerenderTarget => ({ bare: `/events/${eventId}`, locale: 'en', eventId });

  function setup(readHtml: (target: PrerenderTarget) => Promise<string> = async (t) => `<html>disk ${t.eventId}</html>`) {
    const persisted: [PrerenderTarget, string][] = [];
    const persist = vi.fn(async (target: PrerenderTarget, html: string) => {
      persisted.push([target, html]);
    });
    const read = vi.fn(readHtml);
    return { persister: createChainStatePersister(persist, read), persist, read, persisted };
  }

  it('holds every recorded target while unreleased, so a round that ends done makes no PUTs', async () => {
    const { persister, persist, read } = setup();

    persister.record(event(1), '<html>1</html>');
    persister.record(event(2), '<html>2</html>');
    await persister.drain();

    expect(persist).not.toHaveBeenCalled();
    expect(read).not.toHaveBeenCalled();
    expect(persister.held()).toBe(2);
    expect(persister.queued()).toBe(0);
  });

  it('flushes held targets from disk on release, so a continuing round still resolves each one', async () => {
    const { persister, persisted, read } = setup();
    persister.record(event(1), '<html>1</html>');
    persister.record(event(2), '<html>2</html>');

    persister.release();
    await persister.drain();

    expect(read).toHaveBeenCalledTimes(2);
    expect(persisted).toEqual([
      [event(1), '<html>disk 1</html>'],
      [event(2), '<html>disk 2</html>'],
    ]);
    expect(persister.held()).toBe(0);
    expect(persister.queued()).toBe(2);
  });

  it('PUTs straight from memory once released, without a disk read', async () => {
    const { persister, persisted, read } = setup();
    persister.release();

    persister.record(event(3), '<html>rendered 3</html>');
    await persister.drain();

    expect(read).not.toHaveBeenCalled();
    expect(persisted).toEqual([[event(3), '<html>rendered 3</html>']]);
  });

  it('flushes held targets only once across repeated releases', async () => {
    const { persister, persist } = setup();
    persister.record(event(1), '<html>1</html>');

    persister.release();
    persister.release();
    await persister.drain();

    expect(persist).toHaveBeenCalledTimes(1);
  });

  it('never holds or PUTs a home/explore target (no eventId)', async () => {
    const { persister, persist } = setup();

    persister.record({ bare: '/explore', locale: 'en' }, '<html>explore</html>');
    persister.release();
    persister.record({ bare: '/', locale: 'en' }, '<html>home</html>');
    await persister.drain();

    expect(persist).not.toHaveBeenCalled();
    expect(persister.held()).toBe(0);
  });

  it('fails open on a disk-read miss — the other held targets still PUT and drain resolves', async () => {
    const { persister, persisted } = setup(async (t) => {
      if (t.eventId === 1) throw new Error('ENOENT');
      return `<html>disk ${t.eventId}</html>`;
    });
    persister.record(event(1), '<html>1</html>');
    persister.record(event(2), '<html>2</html>');

    persister.release();

    await expect(persister.drain()).resolves.toBeUndefined();
    expect(persisted).toEqual([[event(2), '<html>disk 2</html>']]);
  });
});

describe('chain-state manifest read path (issue #368)', () => {
  const getR2ObjectMock = vi.mocked(getR2Object);

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('partitionByChainState', () => {
    it('routes an event target whose locale:eventId key is in the index to resolved', () => {
      const target: PrerenderTarget = { bare: '/events/42', locale: 'en', eventId: 42 };
      const index: ChainStateIndex = { 'en:42': { resolvedAtRound: 1 } };

      const { resolved, unresolved } = partitionByChainState([target], index);

      expect(resolved).toEqual([target]);
      expect(unresolved).toEqual([]);
    });

    it('routes an event target with no matching index entry to unresolved', () => {
      const target: PrerenderTarget = { bare: '/events/9', locale: 'en', eventId: 9 };
      const index: ChainStateIndex = { 'en:42': { resolvedAtRound: 1 } };

      const { resolved, unresolved } = partitionByChainState([target], index);

      expect(resolved).toEqual([]);
      expect(unresolved).toEqual([target]);
    });

    it('always routes a home/explore target (no eventId) to unresolved, even against a non-empty index', () => {
      const target: PrerenderTarget = { bare: '/explore', locale: 'en' };
      const index: ChainStateIndex = { 'en:42': { resolvedAtRound: 1 } };

      const { resolved, unresolved } = partitionByChainState([target], index);

      expect(resolved).toEqual([]);
      expect(unresolved).toEqual([target]);
    });

    it('keys the index lookup on locale:eventId, so the same eventId under a different locale is unresolved', () => {
      const target: PrerenderTarget = { bare: '/events/42', locale: 'ru', eventId: 42 };
      const index: ChainStateIndex = { 'en:42': { resolvedAtRound: 1 } };

      const { resolved, unresolved } = partitionByChainState([target], index);

      expect(resolved).toEqual([]);
      expect(unresolved).toEqual([target]);
    });
  });

  function snapshotHtmlWithMarker(marker: string): string {
    return `<html><head><script type="application/ld+json">{"@type":"Event","dateModified":"${marker}"}</script></head><body></body></html>`;
  }

  describe('fetchResolvedTarget', () => {
    it('returns a ChangeDetectionResult indistinguishable from a successful classifyTarget result, sourced from R2, when the cached marker still matches', async () => {
      const target: ResolvedTarget = {
        bare: '/events/42',
        locale: 'en',
        eventId: 42,
        updatedAt: '2026-08-01T00:00:00.000Z',
      };
      const cachedHtml = snapshotHtmlWithMarker('2026-08-01T00:00:00.000Z');
      getR2ObjectMock.mockResolvedValue(cachedHtml);
      const manifestHits = new Set<PrerenderTarget>();

      const result = await fetchResolvedTarget('burst-1', target, manifestHits);

      expect(getR2ObjectMock).toHaveBeenCalledWith(`${CHAIN_STATE_PREFIX}burst-1/targets/en-42.html`);
      expect(result).toEqual({ target, unchanged: true, liveHtml: cachedHtml });
      expect(manifestHits.has(target)).toBe(true);
    });

    it('falls back to a fresh production fetch (classifyTarget) on a content-read miss, without marking the target as a manifest hit', async () => {
      const target: ResolvedTarget = { bare: '/events/9', locale: 'en', eventId: 9, updatedAt: '2026-08-01T00:00:00.000Z' };
      getR2ObjectMock.mockResolvedValue(null);
      const fetchMock = vi.fn().mockResolvedValue({ ok: false } as Response);
      vi.stubGlobal('fetch', fetchMock);
      const manifestHits = new Set<PrerenderTarget>();

      const result = await fetchResolvedTarget('burst-1', target, manifestHits);

      expect(fetchMock).toHaveBeenCalledWith(`${PRODUCTION_ORIGIN}/en/events/9`);
      expect(result).toEqual({ target, unchanged: false, liveHtml: null });
      expect(manifestHits.has(target)).toBe(false);

      vi.unstubAllGlobals();
    });

    it('falls back to a fresh production fetch when the cached snapshot predates a later change to the event (stale manifest entry, issue #368 staleness fix)', async () => {
      const target: ResolvedTarget = {
        bare: '/events/42',
        locale: 'en',
        eventId: 42,
        updatedAt: '2026-08-02T00:00:00.000Z',
      };
      getR2ObjectMock.mockResolvedValue(snapshotHtmlWithMarker('2026-08-01T00:00:00.000Z'));
      const freshHtml = snapshotHtmlWithMarker('2026-08-02T00:00:00.000Z');
      const fetchMock = vi.fn().mockResolvedValue({ ok: true, text: () => Promise.resolve(freshHtml) } as Response);
      vi.stubGlobal('fetch', fetchMock);
      const manifestHits = new Set<PrerenderTarget>();

      const result = await fetchResolvedTarget('burst-1', target, manifestHits);

      expect(fetchMock).toHaveBeenCalledWith(`${PRODUCTION_ORIGIN}/en/events/42`);
      expect(result).toEqual({ target, unchanged: true, liveHtml: freshHtml });
      expect(manifestHits.has(target)).toBe(false);

      vi.unstubAllGlobals();
    });
  });
});
