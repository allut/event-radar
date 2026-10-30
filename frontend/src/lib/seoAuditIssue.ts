// .js extension required: this module is also imported (transitively) by
// functions/api/seo-audit.ts, which Cloudflare Pages runs as unbundled ESM.
import { SEO_AUDIT_GITHUB_REPO, SEO_AUDIT_ISSUE_LABEL, SEO_AUDIT_USER_AGENT } from '../constants/seo.js';
import { githubRequest } from './githubRequest.js';

interface GithubIssue {
  number: number;
}

function auditGithubRequest(path: string, token: string, init?: RequestInit): Promise<Response> {
  return githubRequest(SEO_AUDIT_GITHUB_REPO, path, token, SEO_AUDIT_USER_AGENT, init);
}

async function findOpenAuditIssue(token: string): Promise<GithubIssue | null> {
  const res = await auditGithubRequest(
    `/issues?state=open&labels=${encodeURIComponent(SEO_AUDIT_ISSUE_LABEL)}&per_page=1`,
    token,
  );
  if (!res.ok) {
    throw new Error(`GitHub issue lookup failed: ${res.status} ${res.statusText}`);
  }
  const issues = (await res.json()) as GithubIssue[];
  return issues[0] ?? null;
}

/** On a failing audit: comment on the existing open seo-audit-failure issue if
 * one exists (repeat failures don't spam new issues), else file a new one. */
export async function reportAuditFailure(token: string, issues: string[]): Promise<void> {
  const body = `The live SEO audit (issue #54) failed:\n\n${issues.map((issue) => `- ${issue}`).join('\n')}\n\nChecked ${new Date().toISOString()}.`;
  const existing = await findOpenAuditIssue(token);
  if (existing) {
    const res = await auditGithubRequest(`/issues/${existing.number}/comments`, token, {
      method: 'POST',
      body: JSON.stringify({ body }),
    });
    if (!res.ok) {
      throw new Error(`GitHub comment on issue #${existing.number} failed: ${res.status} ${res.statusText}`);
    }
    return;
  }
  const res = await auditGithubRequest('/issues', token, {
    method: 'POST',
    body: JSON.stringify({
      title: 'SEO live audit failing',
      body,
      labels: [SEO_AUDIT_ISSUE_LABEL],
    }),
  });
  if (!res.ok) {
    throw new Error(`GitHub issue creation failed: ${res.status} ${res.statusText}`);
  }
}

/** On a passing audit: close the open seo-audit-failure issue, if any. A
 * no-op when nothing is open, so a passing audit never touches GitHub. Closes
 * *before* commenting (not after) — if the comment call then fails, the
 * worst case is a closed issue with no explanatory comment, which the next
 * failing audit's reportAuditFailure will just reopen-equivalent (file a
 * fresh issue) rather than leaving a stale "closing" comment on an issue
 * that in fact never closed. */
export async function reportAuditRecovery(token: string): Promise<void> {
  const existing = await findOpenAuditIssue(token);
  if (!existing) return;

  const closeRes = await auditGithubRequest(`/issues/${existing.number}`, token, {
    method: 'PATCH',
    body: JSON.stringify({ state: 'closed' }),
  });
  if (!closeRes.ok) {
    throw new Error(`GitHub issue #${existing.number} close failed: ${closeRes.status} ${closeRes.statusText}`);
  }

  const commentRes = await auditGithubRequest(`/issues/${existing.number}/comments`, token, {
    method: 'POST',
    body: JSON.stringify({
      body: `The live SEO audit is passing again as of ${new Date().toISOString()} — closing.`,
    }),
  });
  if (!commentRes.ok) {
    throw new Error(`GitHub comment on issue #${existing.number} failed: ${commentRes.status} ${commentRes.statusText}`);
  }
}
