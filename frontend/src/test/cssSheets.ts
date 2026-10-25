/// <reference types="node" />
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

export const SRC_DIR = join(import.meta.dirname, '..');

// Read off disk: vitest doesn't run CSS through Vite, so `?raw` comes back empty.
// Comments stripped: prose like "the max-width @media rules" would parse as a block.
export const readCss = (path: string): string => readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

export function cssModules(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return cssModules(path);
    return entry.name.endsWith('.module.css') ? [path] : [];
  });
}

// Every `selector-list { body }` rule, flattened (an @media prelude is dropped,
// so rules nested inside it come out as their own entries).
export function rules(css: string): { selectors: string; body: string }[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(m => ({ selectors: m[1], body: m[2] }));
}

// Top-level @media / @container blocks, brace-matched (rule bodies nest one level inside).
export function atRuleBlocks(css: string, kind: 'media' | 'container'): string[] {
  const blocks: string[] = [];
  for (const m of css.matchAll(new RegExp(`@${kind}[^{]*\\{`, 'g'))) {
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
