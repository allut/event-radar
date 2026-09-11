import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { cspScriptSrcSources, inlineScriptHashes } from './csp';

// Reads the real frontend/index.html and frontend/vercel.json off disk (not
// fixtures) — a drift guard is only load-bearing if it exercises the actual
// files that ship, mirroring prerender.test.ts's use of real dist output
// elsewhere in this pipeline.
const FRONTEND_ROOT = path.join(__dirname, '..', '..');

async function readDocumentCsp(): Promise<string> {
  const vercelConfig = JSON.parse(
    await readFile(path.join(FRONTEND_ROOT, 'vercel.json'), 'utf-8'),
  ) as { headers: { source: string; headers: { key: string; value: string }[] }[] };
  const documentHeaders = vercelConfig.headers.find((h) => h.source.includes('api/|_vercel'));
  const csp = documentHeaders?.headers.find((h) => h.key === 'Content-Security-Policy')?.value;
  if (!csp) throw new Error('csp.test.ts: could not find the document CSP in vercel.json');
  return csp;
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
