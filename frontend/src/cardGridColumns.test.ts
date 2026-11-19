// Drift guard (#475): every fixed
// --card-grid-cols count index.css assigns must divide the browse/saved page
// sizes, so each page and each load-more ends on a full grid row.
/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { BROWSE_PAGE_SIZE } from './_generated/sharedConstants';
import { SAVED_EVENTS_PAGE_SIZE } from './constants/feedback';

// Read off disk: vitest doesn't run CSS through Vite, so `?raw` comes back empty.
const indexCss = readFileSync(`${import.meta.dirname}/index.css`, 'utf8');
const fixedColumnCounts = [...indexCss.matchAll(/--card-grid-cols:\s*(\d+)\s*;/g)].map(m => Number(m[1]));

describe('--card-grid-cols', () => {
  it('assigns fixed column counts for the wide band', () => {
    expect(fixedColumnCounts.length).toBeGreaterThan(0);
  });

  it.each([
    ['BROWSE_PAGE_SIZE', BROWSE_PAGE_SIZE],
    ['SAVED_EVENTS_PAGE_SIZE', SAVED_EVENTS_PAGE_SIZE],
  ])('%s is divisible by every fixed column count', (_name, pageSize) => {
    for (const cols of fixedColumnCounts) {
      expect(pageSize % cols).toBe(0);
    }
  });
});
