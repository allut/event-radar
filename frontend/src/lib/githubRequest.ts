import { GITHUB_API_BASE_URL, GITHUB_API_VERSION } from '../constants.js';

/** Authenticated GitHub REST API request, shared by every caller that reads
 * or writes `allut/event-radar` (private, so unauthenticated calls 404).
 * GitHub rejects any request with no User-Agent (403 "Request forbidden by
 * administrative rules") — Node's built-in fetch (undici) sets no default,
 * unlike a browser — so callers must supply one identifying their use case. */
export async function githubRequest(
  repo: string,
  path: string,
  token: string,
  userAgent: string,
  init?: RequestInit,
): Promise<Response> {
  return fetch(`${GITHUB_API_BASE_URL}/repos/${repo}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': GITHUB_API_VERSION,
      'User-Agent': userAgent,
      ...(init?.headers ?? {}),
    },
  });
}
