import { describe, it, expect, vi, afterEach } from 'vitest';
import { githubRequest } from './githubRequest';
import { GITHUB_API_BASE_URL } from '../constants/seo';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('githubRequest', () => {
  it('builds the repo-scoped URL and the auth/version/user-agent headers every caller needs', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => ({ ok: true, status: 200 }) as Response);
    vi.stubGlobal('fetch', fetchMock);

    await githubRequest('allut/event-radar', '/issues', 'tok123', 'seo-audit/1.0');

    expect(fetchMock).toHaveBeenCalledWith(
      `${GITHUB_API_BASE_URL}/repos/allut/event-radar/issues`,
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer tok123',
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'User-Agent': 'seo-audit/1.0',
        }),
      }),
    );
  });

  it('merges caller-supplied init options and headers without dropping the required ones', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => ({ ok: true, status: 201 }) as Response);
    vi.stubGlobal('fetch', fetchMock);

    await githubRequest('allut/event-radar', '/issues', 'tok123', 'prerender/1.0', {
      method: 'POST',
      body: JSON.stringify({ title: 'x' }),
      headers: { 'Content-Type': 'application/json' },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      `${GITHUB_API_BASE_URL}/repos/allut/event-radar/issues`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ title: 'x' }),
        headers: expect.objectContaining({
          Authorization: 'Bearer tok123',
          'User-Agent': 'prerender/1.0',
          'Content-Type': 'application/json',
        }),
      }),
    );
  });

  it('lets a caller-supplied header override a default (init headers spread last)', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => ({ ok: true, status: 200 }) as Response);
    vi.stubGlobal('fetch', fetchMock);

    await githubRequest('allut/event-radar', '/issues', 'tok123', 'default-ua/1.0', {
      headers: { 'User-Agent': 'override-ua/1.0' },
    });

    const init = fetchMock.mock.calls[0][1];
    expect(init?.headers).toMatchObject({ 'User-Agent': 'override-ua/1.0' });
  });

  it('resolves to the fetch Response so callers can branch on status', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => ({ ok: false, status: 404 }) as Response);
    vi.stubGlobal('fetch', fetchMock);

    const res = await githubRequest('allut/event-radar', '/issues/1', 'tok123', 'ua/1.0');
    expect(res.ok).toBe(false);
    expect(res.status).toBe(404);
  });
});
