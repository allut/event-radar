// Lives outside functions/ on purpose: Cloudflare Pages bundles every file
// under that tree into the deployed Worker (underscore-prefixed filenames
// don't exempt them — only whole directories do), and this test's vitest
// import drags in `node:sqlite` via undici, which the Workers bundler can't
// resolve.
import { describe, it, expect, vi } from 'vitest';
import { onRequest } from '../../functions/[[path]]';
import { APP_SHELL_FILENAME } from '../../src/constants/prerender';

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
