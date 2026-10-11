/**
 * Hand-run generator (not wired into `npm run build` — keeps build cost
 * unchanged). Owns the Dial brand identity assets: writes public/favicon.svg
 * and rasterizes every icon Google/iOS/the web-app manifest need, the
 * maskable icon, the email header mark and the 1200×630 OG fallback image.
 *
 * Usage: npx tsx scripts/generate-icons.ts
 */
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { EMAIL_BRAND_MARK_PATH } from '../src/_generated/sharedConstants';
import {
  APPLE_TOUCH_ICON_PATH,
  FAVICON_ICO_PATH,
  ICON_96_PATH,
  ICON_192_PATH,
  ICON_512_PATH,
  ICON_MASKABLE_512_PATH,
  OG_FALLBACK_IMAGE_PATH,
} from '../src/constants/seo';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, '..', 'public');
// Public-facing constants are site-root paths (leading '/'); this script
// writes bare filenames into public/, so strip it once here.
const filename = (crawlablePath: string): string => crawlablePath.slice(1);

/** Raster sizes written straight to public/ as named PNG assets. */
const OUTPUT_SIZES: { size: number; name: string }[] = [
  { size: 96, name: filename(ICON_96_PATH) },
  { size: 192, name: filename(ICON_192_PATH) },
  { size: 512, name: filename(ICON_512_PATH) },
];

/** iOS applies its own rounding/mask to apple-touch-icon — the source must be
 * full-bleed, no transparency, or the mask crops into visible artwork. Every
 * tile but the email mark is a sharp, opaque square, so that holds. */
const APPLE_TOUCH_ICON_SIZE = 180;
const MASKABLE_SIZE = 512;

/** Intermediate raster sizes bundled into favicon.ico (multi-size ICO container). */
const ICO_SIZES = [16, 32, 48];

/** Dark-origin palette (src/index.css): --bg, --text, --text-muted, --accent-ink.
 * The tile is always navy regardless of browser chrome theme, matching the
 * rasters. */
const NAVY = '#13161e';
const INK = '#e4dfd6';
const MUTED = '#7a8ba3';
const GOLD = '#e8a838';

type DialVariant = 'small' | 'large';

/** Dial geometry in DialMark's 24-unit box (components/DialMark/DialMark.tsx).
 * `large` is a faithful copy. `small` (16–48px, email) diverges so it survives
 * tiny sizes: heavier strokes, no inner ring, bigger pivot and tip dot. Both
 * stroke the tip dot in the tile colour so it cuts the rim instead of merging
 * into it. */
function dialMarkup(variant: DialVariant): string {
  const small = variant === 'small';
  const rimR = small ? 10 : 10.25;
  const rimW = small ? 2 : 1.25;
  const handW = small ? 2.25 : 1.5;
  const dotR = small ? 2.75 : 2;
  const pivotR = small ? 2 : 1.4;
  const halo = small ? 1.4 : 1;
  const innerRing = small
    ? ''
    : `<circle cx="12" cy="12" r="5" fill="none" stroke="${INK}" stroke-opacity=".4" stroke-width="1"/>`;
  return (
    `<circle cx="12" cy="12" r="${rimR}" fill="none" stroke="${INK}" stroke-width="${rimW}"/>${innerRing}` +
    `<path d="M12 12 18.6 5.4" stroke="${GOLD}" stroke-width="${handW}"/>` +
    `<circle cx="19.25" cy="4.75" r="${dotR}" fill="${GOLD}" stroke="${NAVY}" stroke-width="${halo}" paint-order="stroke"/>` +
    `<circle cx="12" cy="12" r="${pivotR}" fill="${INK}"/>`
  );
}

/** Navy tile with the Dial centred — sharp unless `radiusRatio` (share of the
 * tile side) rounds it. `fill` is the share of the tile the 24-unit dial box
 * takes. Omit `size` for a scalable file (favicon.svg). */
function tileSvg(variant: DialVariant, fill: number, size?: number, radiusRatio = 0): string {
  const vb = 24 / fill;
  const off = (vb - 24) / 2;
  const rx = +(vb * radiusRatio).toFixed(4);
  const dims = size === undefined ? '' : ` width="${size}" height="${size}"`;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg"${dims} viewBox="0 0 ${+vb.toFixed(4)} ${+vb.toFixed(4)}">` +
    `<rect width="${+vb.toFixed(4)}" height="${+vb.toFixed(4)}"${rx ? ` rx="${rx}"` : ''} fill="${NAVY}"/>` +
    `<g transform="translate(${+off.toFixed(4)} ${+off.toFixed(4)})">${dialMarkup(variant)}</g></svg>`
  );
}

/** Optical-size fills (see docs/design-system.md §9). Maskable keeps the rim
 * and tip dot inside the 40%-radius safe zone: 12.25 units * (512/32) = 196 < 204.8. */
const SMALL_FILL = 0.84;
const LARGE_FILL = 0.68;
const MASKABLE_FILL = 0.75;

const EMAIL_MARK_SIZE = 96; // displayed at 32px in mail — 3x for HiDPI.
/** The email mark sits on the mail body, not under an OS mask, so it rounds
 * itself — a sharp navy square reads as a black box on the light palette.
 * 6/32 is `--radius` at the 32px display size. */
const EMAIL_MARK_RADIUS_RATIO = 6 / 32;
/** The backend embeds the mark as an inline CID attachment (app/email/brand.py),
 * so it needs its own copy — Render deploys `backend/` alone. */
const BACKEND_EMAIL_ASSETS_DIR = path.join(__dirname, '..', '..', 'backend', 'app', 'email', 'assets');

async function screenshotSvgAtSize(
  page: import('playwright').Page,
  size: number,
  svgMarkup: string,
  transparent = false,
): Promise<Buffer> {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(
    `<html><body style="margin:0;padding:0;width:${size}px;height:${size}px;">${svgMarkup}</body></html>`,
  );
  return page.screenshot({ omitBackground: transparent });
}

const fontDataUri = (relPath: string): string =>
  `data:font/woff2;base64,${readFileSync(path.join(__dirname, '..', 'node_modules', relPath)).toString('base64')}`;

/** 1200×630 OG fallback: eyebrow + hairline + stacked wordmark (mirrors
 * BarLogo's "Event" / italic "Radar" split) beside a large Dial. Fonts are
 * embedded as base64 so the render needs no network and cannot silently fall
 * back (CSP aside, this page never ships). */
function ogHtml(): string {
  const scale = 24.4;
  const cx = 900;
  const cy = 315;
  return `<html><head><style>
@font-face{font-family:'Cormorant Garamond';font-weight:500;font-style:normal;src:url(${fontDataUri('@fontsource/cormorant-garamond/files/cormorant-garamond-latin-500-normal.woff2')})}
@font-face{font-family:'Cormorant Garamond';font-weight:500;font-style:italic;src:url(${fontDataUri('@fontsource/cormorant-garamond/files/cormorant-garamond-latin-500-italic.woff2')})}
@font-face{font-family:'Manrope';font-weight:200 800;src:url(${fontDataUri('@fontsource-variable/manrope/files/manrope-latin-wght-normal.woff2')})}
body{margin:0}</style></head><body>
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<rect width="1200" height="630" fill="${NAVY}"/>
<text x="80" y="150" fill="${MUTED}" font-family="Manrope" font-weight="600" font-size="22" letter-spacing="4.4">EVENTRADAR.EE</text>
<rect x="80" y="178" width="96" height="1" fill="${INK}" fill-opacity=".3"/>
<text x="76" y="360" fill="${INK}" font-family="Cormorant Garamond" font-weight="500" font-size="150">Event</text>
<text x="76" y="500" fill="${INK}" font-family="Cormorant Garamond" font-style="italic" font-weight="500" font-size="150">Radar</text>
<g transform="translate(${cx - 12 * scale} ${cy - 12 * scale}) scale(${scale})">${dialMarkup('large')}</g>
</svg></body></html>`;
}

async function renderOgFallback(page: import('playwright').Page): Promise<Buffer> {
  await page.setViewportSize({ width: 1200, height: 630 });
  await page.setContent(ogHtml());
  await page.evaluate(async () => {
    await Promise.all([
      document.fonts.load('500 150px "Cormorant Garamond"'),
      document.fonts.load('italic 500 150px "Cormorant Garamond"'),
      document.fonts.load('600 22px Manrope'),
    ]);
    await document.fonts.ready;
  });
  const loaded = await page.evaluate(
    () =>
      document.fonts.check('500 150px "Cormorant Garamond"') &&
      document.fonts.check('italic 500 150px "Cormorant Garamond"') &&
      document.fonts.check('600 22px Manrope'),
  );
  if (!loaded) throw new Error('OG fonts failed to load — refusing to render a fallback-font image');
  return page.screenshot();
}

/** Builds a multi-size ICO container (ICONDIR + ICONDIRENTRY[] + PNG payloads),
 * per the Microsoft ICO format — PNG-compressed entries are valid since
 * Windows Vista and every modern favicon consumer (including Googlebot). */
function buildIco(pngBuffers: Buffer[], sizes: number[]): Buffer {
  const headerSize = 6 + 16 * pngBuffers.length;
  let offset = headerSize;
  const header = Buffer.alloc(headerSize);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(pngBuffers.length, 4); // image count

  for (let i = 0; i < pngBuffers.length; i++) {
    const entryOffset = 6 + i * 16;
    const size = sizes[i];
    const dim = size >= 256 ? 0 : size; // 0 means 256 in ICO format
    header.writeUInt8(dim, entryOffset); // width
    header.writeUInt8(dim, entryOffset + 1); // height
    header.writeUInt8(0, entryOffset + 2); // color count
    header.writeUInt8(0, entryOffset + 3); // reserved
    header.writeUInt16LE(1, entryOffset + 4); // color planes
    header.writeUInt16LE(32, entryOffset + 6); // bits per pixel
    header.writeUInt32LE(pngBuffers[i].length, entryOffset + 8); // byte size
    header.writeUInt32LE(offset, entryOffset + 12); // offset
    offset += pngBuffers[i].length;
  }

  return Buffer.concat([header, ...pngBuffers]);
}

async function main(): Promise<void> {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();

    writeFileSync(path.join(PUBLIC_DIR, 'favicon.svg'), `${tileSvg('small', SMALL_FILL)}\n`);
    console.log('wrote favicon.svg');

    for (const { size, name } of OUTPUT_SIZES) {
      const buffer = await screenshotSvgAtSize(page, size, tileSvg('large', LARGE_FILL, size));
      writeFileSync(path.join(PUBLIC_DIR, name), buffer);
      console.log(`wrote ${name} (${size}x${size})`);
    }

    const maskable = await screenshotSvgAtSize(page, MASKABLE_SIZE, tileSvg('large', MASKABLE_FILL, MASKABLE_SIZE));
    writeFileSync(path.join(PUBLIC_DIR, filename(ICON_MASKABLE_512_PATH)), maskable);
    console.log(`wrote ${filename(ICON_MASKABLE_512_PATH)} (${MASKABLE_SIZE}x${MASKABLE_SIZE})`);

    // Transparent outside the rounded corners. The public copy keeps already-sent
    // mail (which links it by URL) rendering; new mail embeds the backend copy.
    const emailMark = await screenshotSvgAtSize(
      page,
      EMAIL_MARK_SIZE,
      tileSvg('small', SMALL_FILL, EMAIL_MARK_SIZE, EMAIL_MARK_RADIUS_RATIO),
      true,
    );
    writeFileSync(path.join(PUBLIC_DIR, filename(EMAIL_BRAND_MARK_PATH)), emailMark);
    mkdirSync(BACKEND_EMAIL_ASSETS_DIR, { recursive: true });
    writeFileSync(path.join(BACKEND_EMAIL_ASSETS_DIR, filename(EMAIL_BRAND_MARK_PATH)), emailMark);
    console.log(`wrote ${filename(EMAIL_BRAND_MARK_PATH)} (${EMAIL_MARK_SIZE}x${EMAIL_MARK_SIZE}, public + backend)`);

    const appleTouchIcon = await screenshotSvgAtSize(page, APPLE_TOUCH_ICON_SIZE, tileSvg('large', LARGE_FILL, APPLE_TOUCH_ICON_SIZE));
    writeFileSync(path.join(PUBLIC_DIR, filename(APPLE_TOUCH_ICON_PATH)), appleTouchIcon);
    console.log(`wrote apple-touch-icon.png (${APPLE_TOUCH_ICON_SIZE}x${APPLE_TOUCH_ICON_SIZE})`);

    // Sequential, not Promise.all: every render shares one Playwright `page`,
    // and screenshotSvgAtSize mutates that page's viewport/content —
    // concurrent calls race and silently produce byte-identical payloads.
    const icoBuffers: Buffer[] = [];
    for (const size of ICO_SIZES) {
      icoBuffers.push(await screenshotSvgAtSize(page, size, tileSvg('small', SMALL_FILL, size)));
    }
    const ico = buildIco(icoBuffers, ICO_SIZES);
    writeFileSync(path.join(PUBLIC_DIR, filename(FAVICON_ICO_PATH)), ico);
    console.log(`wrote favicon.ico (${ICO_SIZES.join('/')} multi-size)`);

    writeFileSync(path.join(PUBLIC_DIR, filename(OG_FALLBACK_IMAGE_PATH)), await renderOgFallback(page));
    console.log('wrote og-fallback.png (1200x630)');
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
