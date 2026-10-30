// Ratchet (docs/frontend.md, shared/ table): a frontend constant that mirrors a
// backend one drifts silently, so cross-stack values belong in shared/. This
// counts the comments in constants/*.ts that say "mirrors backend" or name a
// backend constant ("backend PROMOTION_ERROR_*") and pins each file's count. A rise means a new mirror: put the value in shared/ instead. A drop
// means one moved: lower the baseline, so the count only ever tightens.
/// <reference types="node" />
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const MIRROR_COMMENT = /\bmirror(s|ing)?\b.*\bbackend\b/i;
const BACKEND_NAME_COMMENT = /\b[Bb]ackend\s+[A-Z][A-Z0-9]*_[A-Z0-9_]/;
const isMirrorComment = (line: string): boolean => MIRROR_COMMENT.test(line) || BACKEND_NAME_COMMENT.test(line);

// Files left out of the map have a baseline of 0. What remains here is
// frontend-only by nature or waiting on its own domain commit.
const BASELINE: Readonly<Record<string, number>> = {
  'claims.ts': 5,
  'feedback.ts': 1,
  'organizer.ts': 1,
  'organizerPromotions.ts': 4,
  'promotions.ts': 6,
  'routes.ts': 1,
  'sponsored.ts': 1,
};

const counts = Object.fromEntries(
  readdirSync(import.meta.dirname)
    .filter(name => name.endsWith('.ts') && !name.endsWith('.test.ts'))
    .map(name => [name, readFileSync(join(import.meta.dirname, name), 'utf8').split('\n').filter(isMirrorComment).length] as const)
    .filter(([, count]) => count > 0),
);

describe('constants that mirror the backend', () => {
  it.each(Object.keys({ ...BASELINE, ...counts }).sort())('%s matches its baseline', name => {
    const actual = counts[name] ?? 0;
    const baseline = BASELINE[name] ?? 0;
    expect(actual, `${name}: a new backend mirror; put the value in shared/ and import it from _generated/sharedConstants.ts`).toBeLessThanOrEqual(baseline);
    expect(actual, `${name}: a mirror moved to shared/; lower the baseline to ${actual}`).toBeGreaterThanOrEqual(baseline);
  });
});
