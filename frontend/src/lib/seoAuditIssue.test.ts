import { describe, it, expect, vi, afterEach } from 'vitest';
import { reportAuditFailure, reportAuditRecovery } from './seoAuditIssue';

function mockFetchSequence(responses: { ok: boolean; status?: number; json?: unknown }[]) {
  const fn = vi.fn();
  for (const res of responses) {
    fn.mockResolvedValueOnce({
      ok: res.ok,
      status: res.status ?? (res.ok ? 200 : 500),
      statusText: res.ok ? 'OK' : 'Error',
      json: () => Promise.resolve(res.json ?? {}),
    });
  }
  vi.stubGlobal('fetch', fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('reportAuditFailure', () => {
  it('files a new issue when no open seo-audit-failure issue exists', async () => {
    const fetchMock = mockFetchSequence([
      { ok: true, json: [] }, // lookup: none open
      { ok: true, json: { number: 42 } }, // create
    ]);

    await reportAuditFailure('tok', ['sitemap is 9h old']);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [lookupCall, createCall] = fetchMock.mock.calls;
    expect(String(lookupCall[0])).toContain('labels=seo-audit-failure');
    expect(String(createCall[0])).toMatch(/\/issues$/);
    expect(createCall[1].method).toBe('POST');
    const createdBody = JSON.parse(createCall[1].body as string);
    expect(createdBody.labels).toEqual(['seo-audit-failure']);
    expect(createdBody.body).toContain('sitemap is 9h old');
  });

  it('comments on the existing open issue instead of filing a duplicate', async () => {
    const fetchMock = mockFetchSequence([
      { ok: true, json: [{ number: 7 }] }, // lookup: one already open
      { ok: true, json: {} }, // comment
    ]);

    await reportAuditFailure('tok', ['still stale']);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, commentCall] = fetchMock.mock.calls;
    expect(String(commentCall[0])).toMatch(/\/issues\/7\/comments$/);
    expect(commentCall[1].method).toBe('POST');
  });

  it('throws when the GitHub API call fails', async () => {
    mockFetchSequence([{ ok: false, status: 401 }]);
    await expect(reportAuditFailure('bad-token', ['x'])).rejects.toThrow(/GitHub issue lookup failed/);
  });
});

describe('reportAuditRecovery', () => {
  it('is a no-op when no issue is open', async () => {
    const fetchMock = mockFetchSequence([{ ok: true, json: [] }]);
    await reportAuditRecovery('tok');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('closes the open issue, then comments (close first so a failed comment never follows a false "closed" claim)', async () => {
    const fetchMock = mockFetchSequence([
      { ok: true, json: [{ number: 9 }] }, // lookup
      { ok: true, json: {} }, // close
      { ok: true, json: {} }, // comment
    ]);

    await reportAuditRecovery('tok');

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const [, closeCall, commentCall] = fetchMock.mock.calls;
    expect(String(closeCall[0])).toMatch(/\/issues\/9$/);
    expect(closeCall[1].method).toBe('PATCH');
    expect(JSON.parse(closeCall[1].body as string)).toEqual({ state: 'closed' });
    expect(String(commentCall[0])).toMatch(/\/issues\/9\/comments$/);
  });
});
