import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { cspScriptSrcSources, inlineScriptHashes } from './csp';

// Reads the real frontend/index.html and frontend/public/_headers off disk
// (not fixtures) — a drift guard is only load-bearing if it exercises the
// actual files that ship, mirroring prerender.test.ts's use of real dist
// output elsewhere in this pipeline. `public/_headers` (not a repo-root
// `_headers`) because Cloudflare Pages only reads it from the build output
// directory (`dist/`), which Vite populates by copying `public/` verbatim —
// see issue #345.
const FRONTEND_ROOT = path.join(__dirname, '..', '..');

// Cloudflare's `_headers` file is plain text, not JSON: an unindented line
// starts a new path block, and every indented `Key: value` line below it
// belongs to that block, until the next unindented line or EOF. This reads
// the broad `/*` block specifically — not `/api/seo-audit` or
// `/api/prerender-cadence`, which carry their own locked-down CSP with no
// inline-script hash to guard.
async function readDocumentCsp(): Promise<string> {
  const headersFile = await readFile(path.join(FRONTEND_ROOT, 'public', '_headers'), 'utf-8');
  let inDocumentBlock = false;
  for (const line of headersFile.split('\n')) {
    if (!/^\s/.test(line)) {
      inDocumentBlock = line.trim() === '/*';
      continue;
    }
    if (!inDocumentBlock) continue;
    const match = line.match(/^\s+Content-Security-Policy:\s*(.+?)\s*$/);
    if (match) return match[1];
  }
  throw new Error('csp.test.ts: could not find the document CSP in public/_headers');
}

describe('inline script CSP hash stays in sync (theme-revert-on-refresh fix)', () => {
  it('every inline script hash in index.html appears in vercel.json\'s script-src', async () => {
    const html = await readFile(path.join(FRONTEND_ROOT, 'index.html'), 'utf-8');
    const hashes = inlineScriptHashes(html);
    expect(hashes.length).toBeGreaterThan(0);

    const csp = await readDocumentCsp();
    const scriptSrc = cspScriptSrcSources(csp);
    for (const hash of hashes) {
      expect(scriptSrc).toContain(hash);
    }
  });

  it('does not rely on \'unsafe-inline\', which would make the hash pointless', async () => {
    const csp = await readDocumentCsp();
    const scriptSrc = cspScriptSrcSources(csp);
    expect(scriptSrc).not.toContain("'unsafe-inline'");
  });
});
