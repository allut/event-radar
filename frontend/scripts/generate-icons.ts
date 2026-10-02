/**
 * Hand-run generator (not wired into `npm run build` — keeps build cost
 * unchanged) that rasterizes public/favicon.svg into every icon asset
 * Google/iOS/the web-app manifest need.
 *
 * Usage: npx tsx scripts/generate-icons.ts
 */
import { writeFileSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import {
  APPLE_TOUCH_ICON_PATH,
  FAVICON_ICO_PATH,
  ICON_96_PATH,
  ICON_192_PATH,
  ICON_512_PATH,
} from '../src/constants';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, '..', 'public');
const SVG_PATH = path.join(PUBLIC_DIR, 'favicon.svg');

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
 * full-bleed, no transparency, or the mask crops into visible artwork. */
const APPLE_TOUCH_ICON_SIZE = 180;

/** Intermediate raster sizes bundled into favicon.ico (multi-size ICO container). */
const ICO_SIZES = [16, 32, 48];

/** `transparent: true` (the default) drops the page's own white background so
 * favicon.svg's rounded-rect corners come out alpha-transparent instead of a
 * baked-in white square — otherwise browser/OS chrome that isn't `--bg` shows
 * a visible square behind the rounded tile. apple-touch-icon is the one
 * caller that passes `false`: iOS applies its own rounding/mask and expects a
 * full-bleed, opaque source (see APPLE_TOUCH_ICON_SIZE's comment). */
async function screenshotSvgAtSize(
  page: import('playwright').Page,
  size: number,
  transparent = true,
): Promise<Buffer> {
  await page.setViewportSize({ width: size, height: size });
  const svgMarkup = readFileSync(SVG_PATH, 'utf-8');
  await page.setContent(
    `<html><body style="margin:0;padding:0;width:${size}px;height:${size}px;">${svgMarkup}</body></html>`,
  );
  await page.evaluate(() => {
    const svg = document.querySelector('svg');
    if (svg) {
      svg.setAttribute('width', String(document.body.clientWidth));
      svg.setAttribute('height', String(document.body.clientHeight));
    }
  });
  return page.screenshot({ omitBackground: transparent });
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

    for (const { size, name } of OUTPUT_SIZES) {
      const buffer = await screenshotSvgAtSize(page, size);
      writeFileSync(path.join(PUBLIC_DIR, name), buffer);
      console.log(`wrote ${name} (${size}x${size})`);
    }

    const appleTouchIcon = await screenshotSvgAtSize(page, APPLE_TOUCH_ICON_SIZE, false);
    writeFileSync(path.join(PUBLIC_DIR, filename(APPLE_TOUCH_ICON_PATH)), appleTouchIcon);
    console.log(`wrote apple-touch-icon.png (${APPLE_TOUCH_ICON_SIZE}x${APPLE_TOUCH_ICON_SIZE})`);

    // Sequential, not Promise.all: all three renders share one Playwright
    // `page`, and screenshotSvgAtSize mutates that page's viewport/content —
    // concurrent calls race and silently produce byte-identical payloads.
    const icoBuffers: Buffer[] = [];
    for (const size of ICO_SIZES) {
      icoBuffers.push(await screenshotSvgAtSize(page, size));
    }
    const ico = buildIco(icoBuffers, ICO_SIZES);
    writeFileSync(path.join(PUBLIC_DIR, filename(FAVICON_ICO_PATH)), ico);
    console.log(`wrote favicon.ico (${ICO_SIZES.join('/')} multi-size)`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
