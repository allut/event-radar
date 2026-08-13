import { describe, it, expect } from 'vitest';
import { isValidAuditToken } from './seoAuditAuth';

describe('isValidAuditToken', () => {
  it('accepts a matching token', () => {
    expect(isValidAuditToken('secret-token', 'secret-token')).toBe(true);
  });

  it('rejects a mismatched token of the same length', () => {
    expect(isValidAuditToken('secret-tokeX', 'secret-tokeY')).toBe(false);
  });

  it('rejects a mismatched token of a different length', () => {
    expect(isValidAuditToken('short', 'a-much-longer-secret')).toBe(false);
  });

  it('rejects an empty received token against a real secret', () => {
    expect(isValidAuditToken('', 'secret-token')).toBe(false);
  });
});
