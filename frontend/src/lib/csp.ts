import { createHash } from 'node:crypto';
import { JSDOM } from 'jsdom';

// Pure functions — disk I/O stays in the caller (csp.test.ts), mirroring
// seoValidation.ts's shape. Exists to keep the CSP hash in frontend/vercel.json
// from silently drifting out of sync with the inline pre-paint script in
// index.html — a mismatch means the browser refuses to execute the script
// (CSP `script-src` blocks it), which is exactly the theme-revert-on-refresh
// bug this module's caller (csp.test.ts) guards against.
//
// Uses node:crypto, so — like frontend/scripts/prerender.ts — this module is
// Node-only: a build-time/test helper, never imported from app/component code
// that ships to the browser.

/** Every executable inline `<script>` in `html` (no `src`, and no `type` or a
 * JS-executing `type`) hashed sha256-base64, quoted exactly as a CSP
 * `script-src` source-list entry (`'sha256-…'`) — skips `application/ld+json`
 * and any other non-executing inline script, which a browser never runs and
 * a CSP hash entry would be pointless for. Quoted (not bare) so the result
 * compares directly against `cspScriptSrcSources`'s tokens: CSP's grammar
 * requires the single quotes around a hash-source, same as `'self'`/
 * `'unsafe-inline'` — an unquoted hash is not a valid source and the browser
 * ignores it, silently reopening the block this hash exists to lift. */
export function inlineScriptHashes(html: string): string[] {
  const dom = new JSDOM(html);
  const scripts = [...dom.window.document.querySelectorAll('script')];
  const hashes: string[] = [];
  for (const script of scripts) {
    if (script.hasAttribute('src')) continue;
    const type = script.getAttribute('type');
    if (type && type !== 'module' && type !== 'text/javascript') continue;
    const body = script.textContent ?? '';
    hashes.push(`'sha256-${createHash('sha256').update(body, 'utf8').digest('base64')}'`);
  }
  return hashes;
}

/** Parses the `script-src` directive's source list out of a full CSP header
 * value string. Returns an empty array if the directive is absent. */
export function cspScriptSrcSources(csp: string): string[] {
  const directive = csp
    .split(';')
    .map((d) => d.trim())
    .find((d) => d === 'script-src' || d.startsWith('script-src '));
  if (!directive) return [];
  return directive.split(/\s+/).slice(1);
}
