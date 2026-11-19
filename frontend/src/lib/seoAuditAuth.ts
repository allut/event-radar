import { timingSafeEqual } from 'node:crypto';

/** Constant-time comparison for the cron-job.org shared-secret header (mirrors
 * the backend's `/internal/tick` `secrets.compare_digest` pattern). `timingSafeEqual` requires equal-length buffers, so a
 * length mismatch is checked (and short-circuited) first — that check alone
 * leaks only the *length* of a valid token, never its content. */
export function isValidAuditToken(received: string, expected: string): boolean {
  const receivedBuf = Buffer.from(received);
  const expectedBuf = Buffer.from(expected);
  if (receivedBuf.length !== expectedBuf.length) return false;
  return timingSafeEqual(receivedBuf, expectedBuf);
}
