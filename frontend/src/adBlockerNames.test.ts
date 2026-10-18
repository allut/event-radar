import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

// Ad blockers hide elements whose id or class has a bare `ad` or `ads` word,
// so a prototype once vanished. Name promotion UI `promo` or `promotion`.
const SRC_DIR = path.join(__dirname);
const BANNED_WORDS = new Set(['ad', 'ads']);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === '_generated' ? [] : sourceFiles(full);
    return /\.(module\.css|tsx)$/.test(entry.name) && !entry.name.endsWith('.test.tsx') ? [full] : [];
  });
}

function hostile(name: string): boolean {
  return name.split(/[-_]/).some((word) => BANNED_WORDS.has(word.toLowerCase()));
}

function offendingNames(file: string): string[] {
  const text = readFileSync(file, 'utf8');
  const names: string[] = [];
  if (file.endsWith('.css')) {
    const css = text.replace(/\/\*[\s\S]*?\*\//g, '');
    for (const m of css.matchAll(/(?:^|[\s,>+~(])[.#]([A-Za-z_][\w-]*)/g)) names.push(m[1]);
  } else {
    for (const m of text.matchAll(/\bid=["']([^"']+)["']/g)) names.push(...m[1].split(/\s+/));
    for (const m of text.matchAll(/\bstyles\.([A-Za-z_]\w*)/g)) names.push(m[1]);
    for (const m of text.matchAll(/\bstyles\[['"]([\w-]+)['"]\]/g)) names.push(m[1]);
  }
  return names.filter(hostile);
}

describe('ad-blocker-hostile names', () => {
  it('uses no bare ad or ads word in an id or class name', () => {
    const offenders = sourceFiles(SRC_DIR).flatMap((file) =>
      offendingNames(file).map((name) => `${path.relative(SRC_DIR, file)}: ${name}`),
    );
    expect(offenders).toEqual([]);
  });

  it('flags a hostile name', () => {
    expect(hostile('ad')).toBe(true);
    expect(hostile('promo-ads')).toBe(true);
    expect(hostile('adminQueue')).toBe(false);
    expect(hostile('loading')).toBe(false);
  });
});
