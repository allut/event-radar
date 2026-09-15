// Lives outside functions/ on purpose: Cloudflare Pages bundles every file
// under that tree into the deployed Worker (underscore-prefixed filenames
// don't exempt them — only whole directories do), and this test's vitest
// import drags in `node:sqlite` via undici, which the Workers bundler can't
// resolve.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { APP_SHELL_FILENAME } from '../../src/constants';

const proxyToBackend = vi.fn().mockResolvedValue(new Response('proxied', { status: 200 }));
const handleSeoAudit = vi.fn().mockResolvedValue(new Response('seo-audit', { status: 200 }));
const handlePrerenderCadence = vi.fn().mockResolvedValue(new Response('prerender-cadence', { status: 200 }));

vi.mock('../../functions/_shared/apiProxy', () => ({ proxyToBackend: (...args: unknown[]) => proxyToBackend(...args) }));
vi.mock('../../functions/_shared/seoAuditHandler', () => ({ handleSeoAudit: (...args: unknown[]) => handleSeoAudit(...args) }));
vi.mock('../../functions/_shared/prerenderCadenceHandler', () => ({
  handlePrerenderCadence: (...args: unknown[]) => handlePrerenderCadence(...args),
}));

const { onRequest } = await import('../../functions/[[path]]');

function makeContext(path: string, method = 'GET', assetResponses?: Response[]) {
  const responses = assetResponses ?? [new Response(null, { status: 404 }), new Response('<html>shell</html>', { status: 200 })];
  const fetchAssets = vi.fn();
  for (const response of responses) fetchAssets.mockResolvedValueOnce(response);
  return {
    context: {
      request: new Request(`https://eventradar.ee${path}`, { method }),
      env: { ASSETS: { fetch: fetchAssets } },
    },
    fetchAssets,
  };
}

describe('root Function dispatch (issue #345, restructured 2026-09-15)', () => {
  afterEach(() => {
    proxyToBackend.mockClear();
    handleSeoAudit.mockClear();
    handlePrerenderCadence.mockClear();
  });

  it('dispatches /api/seo-audit to the seo-audit handler, not the backend proxy', async () => {
    const { context } = makeContext('/api/seo-audit', 'POST');

    const response = await onRequest(context);

    expect(handleSeoAudit).toHaveBeenCalledTimes(1);
    expect(proxyToBackend).not.toHaveBeenCalled();
    expect(await response.text()).toBe('seo-audit');
  });

  it('dispatches /api/prerender-cadence to the prerender-cadence handler, not the backend proxy', async () => {
    const { context } = makeContext('/api/prerender-cadence', 'POST');

    const response = await onRequest(context);

    expect(handlePrerenderCadence).toHaveBeenCalledTimes(1);
    expect(proxyToBackend).not.toHaveBeenCalled();
    expect(await response.text()).toBe('prerender-cadence');
  });

  it('dispatches every other /api/* path to the backend proxy — the bug this fixed', async () => {
    const { context } = makeContext('/api/explore?for_you=false', 'GET');

    const response = await onRequest(context);

    expect(proxyToBackend).toHaveBeenCalledTimes(1);
    expect(handleSeoAudit).not.toHaveBeenCalled();
    expect(handlePrerenderCadence).not.toHaveBeenCalled();
    expect(await response.text()).toBe('proxied');
  });

  it('does not dispatch a non-/api path to the backend proxy', async () => {
    const { context, fetchAssets } = makeContext('/events/42');

    await onRequest(context);

    expect(proxyToBackend).not.toHaveBeenCalled();
    expect(fetchAssets).toHaveBeenCalled();
  });
});

describe('SPA-fallback catch-all', () => {
  it('serves the real asset directly when one exists (issue #354)', async () => {
    const realAsset = new Response('console.log(1)', { status: 200 });
    const { context, fetchAssets } = makeContext('/assets/index-abc123.js', 'GET', [realAsset]);

    const response = await onRequest(context);

    expect(fetchAssets).toHaveBeenCalledTimes(1);
    const firstRequest = fetchAssets.mock.calls[0][0] as Request;
    expect(firstRequest.url).toBe('https://eventradar.ee/assets/index-abc123.js');
    expect(await response.text()).toBe('console.log(1)');
  });

  it('serves app-shell.html for an unmatched client-side route', async () => {
    const { context, fetchAssets } = makeContext('/events/42');

    const response = await onRequest(context);

    expect(fetchAssets).toHaveBeenCalledTimes(2);
    const shellRequest = fetchAssets.mock.calls[1][0] as Request;
    // Extensionless "pretty path" — ASSETS.fetch applies its own .html-stripping
    // redirect rule first, so requesting the .html filename directly would hand
    // back a 308 instead of the shell's content.
    expect(shellRequest.url).toBe(`https://eventradar.ee/${APP_SHELL_FILENAME.replace(/\.html$/, '')}`);
    expect(await response.text()).toBe('<html>shell</html>');
  });

  it('serves app-shell.html for a locale-prefixed route', async () => {
    const { context, fetchAssets } = makeContext('/en/saved');

    await onRequest(context);

    const shellRequest = fetchAssets.mock.calls[1][0] as Request;
    expect(shellRequest.url).toBe(`https://eventradar.ee/${APP_SHELL_FILENAME.replace(/\.html$/, '')}`);
  });

  it('rejects a non-GET/HEAD method', async () => {
    const { context, fetchAssets } = makeContext('/events/42', 'POST');

    const response = await onRequest(context);

    expect(response.status).toBe(405);
    expect(fetchAssets).not.toHaveBeenCalled();
  });

  it('serves app-shell.html for a HEAD request', async () => {
    const { context, fetchAssets } = makeContext('/settings', 'HEAD');

    const response = await onRequest(context);

    expect(fetchAssets).toHaveBeenCalledTimes(2);
    expect(response.status).toBe(200);
  });
});
