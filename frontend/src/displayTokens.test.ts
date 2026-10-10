// Drift guard (#465, docs/design-system.md §4): browser zoom shrinks
// the CSS viewport, so a vw-driven display token only grows once it hits its
// lower bound. Each token must reach 2x its 100% size by 300% zoom (Safari's
// cap) — guaranteed when max ÷ min ≤ 1.5 — with rem bounds so the token also
// follows the user's browser default font size. And no stylesheet may swap a
// display-token selector for another size inside an @media block: a zoomed
// desktop window crosses those breakpoints and the text would shrink.
/// <reference types="node" />
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

// Read off disk: vitest doesn't run CSS through Vite, so `?raw` comes back empty.
// Comments stripped: prose like "the max-width @media rules" would parse as a block.
const readCss = (path: string): string => readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const indexCss = readCss(`${import.meta.dirname}/index.css`);
// At zoom z a token renders at least z × min, so 300% zoom reaches 2× its
// 100% size (at most max) whenever max ÷ min ≤ 3 / 2.
const MAX_DISPLAY_RATIO = 1.5;
const DISPLAY_FONT_SIZE = /font(?:-size)?\s*:[^;}]*var\(--font-size-display-/;
const ANY_FONT_SIZE = /font(?:-size)?\s*:/;
const tokens = [...indexCss.matchAll(/(--font-size-display-[\w-]+):\s*([^;]+);/g)].map(m => [m[1], m[2].trim()] as const);

function parseClamp(value: string): { min: string; max: string } | null {
  const m = /^clamp\(\s*([^,]+),\s*[^,]+,\s*([^,)]+)\)$/.exec(value);
  return m ? { min: m[1].trim(), max: m[2].trim() } : null;
}

function cssModules(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return cssModules(path);
    return entry.name.endsWith('.module.css') ? [path] : [];
  });
}

// Every `selector-list { body }` rule, flattened (an @media prelude is dropped,
// so rules nested inside it come out as their own entries).
function rules(css: string): { selectors: string; body: string }[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(m => ({ selectors: m[1], body: m[2] }));
}

const classesIn = (selectors: string): string[] => [...selectors.matchAll(/\.([\w-]+)/g)].map(m => m[1]);

// Top-level @media blocks, brace-matched (rule bodies nest one level inside).
function mediaBlocks(css: string): string[] {
  const blocks: string[] = [];
  for (const m of css.matchAll(/@media[^{]*\{/g)) {
    let depth = 1;
    let i = m.index + m[0].length;
    while (depth > 0 && i < css.length) {
      if (css[i] === '{') depth++;
      if (css[i] === '}') depth--;
      i++;
    }
    blocks.push(css.slice(m.index, i));
  }
  return blocks;
}

describe('--font-size-display-* tokens', () => {
  it('are defined', () => {
    expect(tokens.length).toBeGreaterThan(0);
  });

  it.each(tokens)('%s is a clamp() with rem bounds', (_name, value) => {
    const clamp = parseClamp(value);
    expect(clamp).not.toBeNull();
    expect(clamp!.min).toMatch(/^[\d.]+rem$/);
    expect(clamp!.max).toMatch(/^[\d.]+rem$/);
  });

  it.each(tokens)(`%s keeps max ÷ min ≤ ${MAX_DISPLAY_RATIO} (2x by 300% zoom)`, (_name, value) => {
    const { min, max } = parseClamp(value)!;
    expect(parseFloat(max) / parseFloat(min)).toBeLessThanOrEqual(MAX_DISPLAY_RATIO);
  });

  it('are never redefined inside an @media block', () => {
    for (const block of mediaBlocks(indexCss)) {
      expect(block).not.toMatch(/--font-size-display-/);
    }
  });
});

describe('display-token consumers', () => {
  const sheets = cssModules(import.meta.dirname).map(path => [path.slice(import.meta.dirname.length + 1), readCss(path)] as const);
  const consumers = sheets
    .map(([path, css]) => {
      const classes = rules(css).filter(r => DISPLAY_FONT_SIZE.test(r.body)).flatMap(r => classesIn(r.selectors));
      return [path, css, new Set(classes)] as const;
    })
    .filter(([, , classes]) => classes.size > 0);

  it('exist', () => {
    expect(consumers.length).toBeGreaterThan(0);
  });

  it.each(consumers)('%s never resizes a display-token selector inside @media', (_path, css, classes) => {
    for (const block of mediaBlocks(css)) {
      for (const rule of rules(block.slice(block.indexOf('{') + 1))) {
        if (!ANY_FONT_SIZE.test(rule.body)) continue;
        const resized = classesIn(rule.selectors).filter(cls => classes.has(cls));
        expect(resized, `${rule.selectors.trim()} { ${rule.body.trim()} }`).toEqual([]);
      }
    }
  });
});
