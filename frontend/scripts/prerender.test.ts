import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { buildRobotsTxt, isPreviewBuild, logZeroProgressAbort, main, selectValidationTargets } from './prerender';
import type { PrerenderTarget } from './prerender';
import type { RoundMarker } from '../src/lib/prerenderChain';
import { CRAWLABLE_ICON_PATHS, SITEMAP_PATH } from '../src/constants';

function makeTarget(bare: string): PrerenderTarget {
  return { bare, locale: 'en' };
}

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
  it('is true when VERCEL_ENV is preview', () => {
    expect(isPreviewBuild({ VERCEL_ENV: 'preview' } as NodeJS.ProcessEnv)).toBe(true);
  });

  it('is false for production', () => {
    expect(isPreviewBuild({ VERCEL_ENV: 'production' } as NodeJS.ProcessEnv)).toBe(false);
  });

  it('is false for local/dev runs where VERCEL_ENV is unset', () => {
    expect(isPreviewBuild({} as NodeJS.ProcessEnv)).toBe(false);
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
    for (const path of ['/', '/en', '/ru', '/events/1', '/en/events/1', '/ru/events/1']) {
      expect(isAllowed(robotsTxt, path)).toBe(true);
    }
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

describe('main — Preview short-circuit (issue #95)', () => {
  let logSpy: ReturnType<typeof vi.spyOn>;
  let fetchSpy: ReturnType<typeof vi.spyOn>;
  const originalVercelEnv = process.env.VERCEL_ENV;

  beforeEach(() => {
    logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      throw new Error('fetch must not be called on a Preview build');
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    if (originalVercelEnv === undefined) {
      delete process.env.VERCEL_ENV;
    } else {
      process.env.VERCEL_ENV = originalVercelEnv;
    }
  });

  it('exits before any rendering, sitemap/robots, validation, or fetch work when VERCEL_ENV=preview', async () => {
    process.env.VERCEL_ENV = 'preview';

    await expect(main()).resolves.toBeUndefined();

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(logSpy).toHaveBeenCalledWith(expect.stringContaining('skipping prerender pass'));
  });
});
