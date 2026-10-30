// The registry-code format check agrees with the backend's on every shared case
// (shared/fixtures/promotion_registry_codes.json, also run by the backend suite).
/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { PROMOTION_REGISTRY_CODE_RE } from './promotions';

const { cases } = JSON.parse(
  readFileSync(join(import.meta.dirname, '../../../shared/fixtures/promotion_registry_codes.json'), 'utf8'),
) as { cases: { code: string; valid: boolean; why: string }[] };

describe('PROMOTION_REGISTRY_CODE_RE', () => {
  it.each(cases)('$why', ({ code, valid }) => {
    expect(PROMOTION_REGISTRY_CODE_RE.test(code)).toBe(valid);
  });
});
