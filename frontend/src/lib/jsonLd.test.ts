import { describe, expect, it } from 'vitest';
import { serializeJsonLd } from './jsonLd';

describe('serializeJsonLd', () => {
  it('escapes every "<" so a "</script" payload cannot close the tag', () => {
    const payload = { name: '</script><meta http-equiv="refresh" content="0;url=https://evil.example">' };
    const out = serializeJsonLd(payload);
    expect(out).not.toContain('<');
    expect(JSON.parse(out)).toEqual(payload);
  });
});
