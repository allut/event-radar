// Lives outside functions/ on purpose: Cloudflare Pages bundles every file
// under that tree into the deployed Worker (underscore-prefixed filenames
// don't exempt them — only whole directories do), and this test's vitest
// import drags in `node:sqlite` via undici, which the Workers bundler can't
// resolve.
import { describe, it, expect, vi } from 'vitest';
import { onRequest } from '../../functions/[[path]]';
import { APP_SHELL_FILENAME } from '../../src/constants';

function makeContext(path: string, method = 'GET') {
  const fetchAssets = vi.fn().mockResolvedValue(new Response('<html>shell</html>', { status: 200 }));
  return {
    context: {
      request: new Request(`https://eventradar.ee${path}`, { method }),
      env: { ASSETS: { fetch: fetchAssets } },
    },
    fetchAssets,
  };
}

describe('SPA-fallback catch-all', () => {
  it('serves app-shell.html for an unmatched client-side route', async () => {
    const { context, fetchAssets } = makeContext('/events/42');

    const response = await onRequest(context);

    expect(fetchAssets).toHaveBeenCalledTimes(1);
    const assetsRequest = fetchAssets.mock.calls[0][0] as Request;
    expect(assetsRequest.url).toBe(`https://eventradar.ee/${APP_SHELL_FILENAME}`);
    expect(await response.text()).toBe('<html>shell</html>');
  });

  it('serves app-shell.html for a locale-prefixed route', async () => {
    const { context, fetchAssets } = makeContext('/en/saved');

    await onRequest(context);

    const assetsRequest = fetchAssets.mock.calls[0][0] as Request;
    expect(assetsRequest.url).toBe(`https://eventradar.ee/${APP_SHELL_FILENAME}`);
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

    expect(fetchAssets).toHaveBeenCalledTimes(1);
    expect(response.status).toBe(200);
  });
});
