/**
 * Hand-run generator (not wired into `npm run build`). Writes a standalone
 * prototype shell built from the real `src/index.css`, scoped to `#app`, with
 * Manrope and Cormorant Garamond, a working theme switch and a modal mount
 * point inside `#app`, so every themed token resolves in the prototype.
 *
 * Usage: npx tsx scripts/prototype-shell.ts <out.html>
 * Then fill `#proto-content` with markup that uses the real shared classes'
 * tokens; never copy the palette by hand.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const INDEX_CSS_PATH = path.join(__dirname, '..', 'src', 'index.css');
const FONTS_HREF =
  'https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,600&family=Manrope:wght@400;500;600;700&display=swap';

/** Re-roots the document-level selectors (`:root`, `html`, `body`) onto `#app`. */
export function scopeToApp(css: string): string {
  return css
    .replace(/^:root/gm, '#app')
    .replace(/^(\s+):root\b/gm, '$1#app')
    .replace(/^html \{/gm, '#app {')
    .replace(/^body \{/gm, '#app {');
}

export function buildShell(css: string): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Event Radar prototype</title>
<link rel="stylesheet" href="${FONTS_HREF}">
<style>
${scopeToApp(css)}
.protoBar { display: flex; justify-content: flex-end; padding: var(--space-3, 12px); }
</style>
</head>
<body>
<div id="app" data-theme="dark">
  <div class="protoBar"><button id="themeSwitch" type="button">Theme: dark</button></div>
  <main id="proto-content"><!-- prototype markup goes here --></main>
  <!-- Mount every modal and dialog here, inside #app, so it inherits the theme. -->
  <div id="modal-root"></div>
</div>
<script>
  const app = document.getElementById('app');
  const toggle = document.getElementById('themeSwitch');
  toggle.addEventListener('click', () => {
    const next = app.dataset.theme === 'dark' ? 'light' : 'dark';
    app.dataset.theme = next;
    toggle.textContent = 'Theme: ' + next;
  });
</script>
</body>
</html>
`;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const out = process.argv[2];
  if (!out) {
    console.error('Usage: npx tsx scripts/prototype-shell.ts <out.html>');
    process.exit(1);
  }
  writeFileSync(out, buildShell(readFileSync(INDEX_CSS_PATH, 'utf8')));
  console.log(`Wrote ${out}`);
}
