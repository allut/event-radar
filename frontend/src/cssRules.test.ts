// Drift guard: rules the stylesheets must keep
// that neither ESLint nor tsc can see. Runs over every .module.css plus index.css.
import { SRC_DIR, atRuleBlocks, composedTies, cssModules, readCss, rules } from './test/cssSheets';
import { COMPOSED_TIE_BASELINE } from './test/composedTieBaseline';

const indexCss = readCss(`${SRC_DIR}/index.css`);
const sheets = [
  ['index.css', indexCss] as const,
  ...cssModules(SRC_DIR).map(path => [path.slice(SRC_DIR.length + 1), readCss(path)] as const),
];
const modules = sheets.filter(([path]) => path !== 'index.css');

// `var(--x, 0s)` fallbacks (nested ones too) are token use, not literals.
function stripVars(value: string): string {
  let out = value;
  let prev: string;
  do {
    prev = out;
    out = out.replace(/var\([^()]*\)/g, '');
  } while (out !== prev);
  return out;
}

const declarations = (body: string): { prop: string; value: string }[] =>
  body
    .split(';')
    .map(d => d.trim())
    .filter(Boolean)
    .map(d => {
      const i = d.indexOf(':');
      return { prop: d.slice(0, i).trim(), value: d.slice(i + 1).trim() };
    });

describe('stylesheet rules', () => {
  it('cover index.css and the modules', () => {
    expect(modules.length).toBeGreaterThan(0);
  });

  it.each(sheets)('%s has no composes inside @media or @container', (_path, css) => {
    for (const kind of ['media', 'container'] as const) {
      for (const block of atRuleBlocks(css, kind)) {
        expect(block, `composes inside @${kind}: compose on a top-level rule`).not.toMatch(/\bcomposes\s*:/);
      }
    }
  });

  it.each(sheets)('%s has no literal durations or radii', (_path, css) => {
    for (const { selectors, body } of rules(css)) {
      for (const { prop, value } of declarations(body)) {
        const bare = stripVars(value);
        if (/^(animation|transition)/.test(prop)) {
          // 1ms is the reduced-motion idiom: it still fires animationend, 0s would not.
          const literal = bare.replace(/\b1ms\b/g, '');
          expect(literal, `${selectors.trim()} { ${prop} }: use an --anim-* token`).not.toMatch(/\d+(\.\d+)?m?s\b/);
        }
        if (/^border(-(top|bottom)-(left|right))?-radius$/.test(prop)) {
          expect(bare, `${selectors.trim()} { ${prop} }: use a --radius-* token`).not.toMatch(/\d(?:px|rem|em\b|%)/);
        }
      }
    }
  });

  const breakpoints = [...indexCss.matchAll(/--bp-[\w-]+:\s*(\d+)px/g)].map(m => Number(m[1]));

  it('define breakpoint doc tokens', () => {
    expect(breakpoints.length).toBeGreaterThan(0);
  });

  it.each(sheets)('%s takes @media widths from the --bp-* doc tokens', (_path, css) => {
    for (const block of atRuleBlocks(css, 'media')) {
      const prelude = block.slice(0, block.indexOf('{'));
      for (const m of prelude.matchAll(/(?:min|max)-width:\s*(\d+)px/g)) {
        const width = Number(m[1]);
        // One off a token is the min/max pair idiom (max 1279 against 1280).
        const known = breakpoints.some(bp => Math.abs(bp - width) <= 1);
        expect(known, `@media ${m[0]}: add a --bp-* doc token to index.css`).toBe(true);
      }
    }
  });

  it('has no rule block of 6+ declarations duplicated across modules', () => {
    const MIN_DECLARATIONS = 6;
    const seen = new Map<string, Set<string>>();
    for (const [path, css] of modules) {
      for (const { body } of rules(css)) {
        const decls = declarations(body)
          .filter(d => d.prop !== 'composes')
          .map(d => `${d.prop}:${d.value.replace(/\s+/g, ' ')}`);
        if (decls.length < MIN_DECLARATIONS) continue;
        const key = decls.sort().join(';');
        seen.set(key, (seen.get(key) ?? new Set()).add(path));
      }
    }
    const dupes = [...seen.values()]
      .filter(paths => paths.size > 1)
      .map(paths => {
        const files = [...paths];
        const shared = files.filter(f => f.startsWith('components/shared/'));
        return `${files.join(' + ')}${shared.length ? ` (shared: ${shared.join(', ')})` : ''}`;
      });
    expect(dupes, 'compose from a shared module instead of copying the block').toEqual([]);
  });

  describe('overrides of a composed property', () => {
    const ties = composedTies(cssModules(SRC_DIR));
    const baseline = new Set(COMPOSED_TIE_BASELINE);

    it('out-rank the shared rule', () => {
      const added = ties.filter(tie => !baseline.has(tie));
      expect(added, 'double or qualify the local selector').toEqual([]);
    });

    it('keep the baseline down to ties that still exist', () => {
      const fixed = COMPOSED_TIE_BASELINE.filter(tie => !ties.includes(tie));
      expect(fixed, 'fixed: delete these lines from test/composedTieBaseline.ts').toEqual([]);
    });
  });
});
