/// <reference types="node" />
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';

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

const declaredProps = (body: string): string[] =>
  body
    .split(';')
    .map(d => d.slice(0, d.indexOf(':')).trim())
    .filter(prop => prop && prop !== 'composes');

const selectorList = (selectors: string): string[] => selectors.split(',').map(s => s.trim().replace(/\s+/g, ' '));

const classToken = (name: string): RegExp => new RegExp(`\\.${name}(?![\\w-])`, 'g');

/** Every [file, class] a module's class composes, followed transitively. */
function composedClasses(file: string, cls: string, seen = new Set<string>()): [string, string][] {
  const out: [string, string][] = [];
  for (const { selectors, body } of rules(readCss(file))) {
    if (!selectorList(selectors).includes(`.${cls}`)) continue;
    for (const m of body.matchAll(/composes\s*:\s*([\w\s-]+?)(?:\s+from\s+['"]([^'"]+)['"])?\s*(?:;|$)/g)) {
      const source = m[2] ? resolve(dirname(file), m[2]) : file;
      for (const name of m[1].trim().split(/\s+/)) {
        const key = `${source}#${name}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push([source, name], ...composedClasses(source, name, seen));
      }
    }
  }
  return out;
}

/**
 * Local rules that set a property a class composed from another module also
 * sets, at the same selector shape and so the same specificity. Vite may bundle
 * either module first, so source order, not the author, picks the winner.
 * One entry per property:
 * `routes/X.module.css .a:hover {color} = components/shared/Button.module.css .btnOutline:hover`.
 */
export function composedTies(files: string[]): string[] {
  const ties = new Set<string>();
  for (const file of files) {
    const local = rules(readCss(file)).map(r => ({ selectors: selectorList(r.selectors), props: declaredProps(r.body) }));
    const classes = new Set(local.flatMap(r => r.selectors).filter(s => /^\.[\w-]+$/.test(s)).map(s => s.slice(1)));
    for (const cls of classes) {
      for (const [source, name] of composedClasses(file, cls)) {
        if (source === file) continue; // one file's source order is stable
        for (const shared of rules(readCss(source))) {
          const sharedProps = declaredProps(shared.body);
          for (const sharedSelector of selectorList(shared.selectors)) {
            if (!classToken(name).test(sharedSelector)) continue;
            const mapped = sharedSelector.replace(classToken(name), `.${cls}`);
            for (const rule of local) {
              if (!rule.selectors.includes(mapped)) continue;
              for (const prop of rule.props.filter(p => sharedProps.includes(p))) {
                ties.add(`${relative(SRC_DIR, file)} ${mapped} {${prop}} = ${relative(SRC_DIR, source)} ${sharedSelector}`);
              }
            }
          }
        }
      }
    }
  }
  return [...ties].sort();
}
