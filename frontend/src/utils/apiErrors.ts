import { ApiError } from '../api/client';
import { CLAIM_ERROR_CODE_JUSTIFICATION_REQUIRED } from '../_generated/sharedConstants';

/** A caught error's server-provided message when it's an ApiError, else a
 * caller-supplied fallback — the `err instanceof ApiError ? err.message :
 * <fallback>` ternary repeated at every mutation's onError. */
export function apiErrorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** True when a claim-creation failure is specifically "needs a justification"
 * (#428's Series-claim gate) — the one claim-creation error ClaimEventPicker/
 * ClaimStrip react to structurally (reveal the reason field) rather than
 * just display, so both share this check instead of duplicating the
 * ApiError.code comparison. */
export function isClaimJustificationRequiredError(err: unknown): boolean {
  return err instanceof ApiError && err.code === CLAIM_ERROR_CODE_JUSTIFICATION_REQUIRED;
}
