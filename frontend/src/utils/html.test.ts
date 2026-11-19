import { describe, it, expect } from 'vitest';
import { safeUrl, sanitizeHtml, truncateForMeta } from './html';

describe('safeUrl', () => {
  it('passes http URLs', () => {
    expect(safeUrl('http://example.com')).toBe('http://example.com');
  });

  it('passes https URLs', () => {
    expect(safeUrl('https://example.com/path?q=1')).toBe('https://example.com/path?q=1');
  });

  it('rejects javascript: scheme', () => {
    expect(safeUrl('javascript:alert(1)')).toBeNull();
  });

  it('rejects data: scheme', () => {
    expect(safeUrl('data:text/html,<h1>x</h1>')).toBeNull();
  });

  it('returns null for malformed URL', () => {
    expect(safeUrl('not a url')).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(safeUrl('')).toBeNull();
  });

  it('returns null for null input', () => {
    expect(safeUrl(null)).toBeNull();
  });

  it('returns null for undefined input', () => {
    expect(safeUrl(undefined)).toBeNull();
  });
});

describe('sanitizeHtml', () => {
  it('allows safe tags', () => {
    const result = sanitizeHtml('<p>Hello <strong>world</strong></p>');
    expect(result).toContain('<p>');
    expect(result).toContain('<strong>');
  });

  it('strips script tags', () => {
    const result = sanitizeHtml('<p>ok</p><script>alert(1)</script>');
    expect(result).not.toContain('<script>');
    expect(result).toContain('<p>ok</p>');
  });

  it('strips onerror attributes', () => {
    const result = sanitizeHtml('<img src="x" onerror="alert(1)">');
    expect(result).not.toContain('onerror');
  });

  it('allows href on anchor tags', () => {
    const result = sanitizeHtml('<a href="https://example.com">link</a>');
    expect(result).toContain('href');
  });

  it('strips disallowed attributes', () => {
    const result = sanitizeHtml('<p class="foo" style="color:red">text</p>');
    expect(result).not.toContain('class=');
    expect(result).not.toContain('style=');
  });

  it('forces rel="noopener noreferrer" and target="_blank" on anchors', () => {
    const result = sanitizeHtml('<a href="https://example.com">link</a>');
    expect(result).toContain('rel="noopener noreferrer"');
    expect(result).toContain('target="_blank"');
  });

  it('overrides an attacker-supplied rel/target on anchors', () => {
    const result = sanitizeHtml(
      '<a href="https://evil.example" rel="opener" target="_self">link</a>'
    );
    expect(result).toContain('rel="noopener noreferrer"');
    expect(result).toContain('target="_blank"');
    expect(result).not.toContain('rel="opener"');
  });
});

describe('truncateForMeta', () => {
  it('returns text unchanged when already within the limit', () => {
    expect(truncateForMeta('Short text.', 155)).toBe('Short text.');
  });

  it('truncates at a word boundary and appends an ellipsis when over the limit', () => {
    const text = 'This is a fairly long sentence that will definitely exceed a very short limit.';
    const result = truncateForMeta(text, 20);
    expect(result.length).toBeLessThanOrEqual(21); // 20 + ellipsis char
    expect(result.endsWith('…')).toBe(true);
    expect(result).not.toMatch(/\s…$/); // no dangling space before the ellipsis
    expect(text.startsWith(result.slice(0, -1))).toBe(true); // never cuts mid-word into a new word
  });

  it('never cuts a word in half', () => {
    const result = truncateForMeta('alpha beta gamma delta epsilon', 12);
    const withoutEllipsis = result.replace(/…$/, '');
    expect(['alpha', 'alpha beta']).toContain(withoutEllipsis);
  });

  it('never splits a surrogate pair (emoji) at the cut boundary', () => {
    const text = '🎉'.repeat(20); // each emoji is a 2-code-unit surrogate pair
    const result = truncateForMeta(text, 15); // odd limit — would split mid-pair on a raw slice()
    const withoutEllipsis = result.replace(/…$/, '');
    expect([...withoutEllipsis].every((ch) => ch === '🎉')).toBe(true);
    expect(withoutEllipsis).not.toMatch(/�/); // no replacement/mojibake character
  });
});
