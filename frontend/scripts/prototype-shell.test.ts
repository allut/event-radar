import { describe, expect, it } from 'vitest';
import { buildShell, scopeToApp } from './prototype-shell';

describe('prototype shell', () => {
  it('re-roots document selectors onto #app, including inside @media', () => {
    const css = ':root {\n  --a: 1;\n}\n:root[data-theme="light"] {\n  --a: 2;\n}\n@media (min-width: 2000px) {\n  :root {\n    --a: 3;\n  }\n}\nhtml {\n  color: red;\n}\nbody {\n  margin: 0;\n}\n';
    const scoped = scopeToApp(css);
    expect(scoped).not.toMatch(/:root|^html|^body/m);
    expect(scoped).toContain('#app[data-theme="light"]');
    expect(scoped).toContain('  #app {');
  });

  it('mounts the modal root inside #app and wires the theme switch', () => {
    const html = buildShell('');
    expect(html.indexOf('id="modal-root"')).toBeLessThan(html.indexOf('</div>\n<script>'));
    expect(html).toContain('id="themeSwitch"');
  });
});
