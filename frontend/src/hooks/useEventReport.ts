import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { QUERY_KEYS } from '../constants/api';
import { patchCachedEvent } from '../utils';

export interface UseEventReportResult {
  reportOpen: boolean;
  /** Base `reported` flag (from the event payload) OR'd with the optimistic
   * flip set right after a successful submit — the same shape both
   * EventDetail and EventCard need for their overflow menu's disabled row. */
  reported: boolean;
  openReportModal: () => void;
  closeReportModal: () => void;
  handleReportSubmitted: () => void;
}

/** Shared Report-event flow behind EventDetail's and EventCard's overflow
 * menu (issue #128): takes `authed`/`onLoginRequired` from the caller (no
 * per-card router/auth subscription, issue #455) and gates the modal open on auth (redirecting signed-out
 * clicks to /login, mirroring Share's no-auth-gate exception), and on a
 * successful submit flips the local "reported" state and invalidates every
 * read surface the `reported` field appears on. */
export function useEventReport(
  baseReported: boolean,
  eventId: number | undefined,
  authed: boolean,
  onLoginRequired: () => void,
): UseEventReportResult {
  const queryClient = useQueryClient();
  const [reportOpen, setReportOpen] = useState(false);
  const [reportedOverride, setReportedOverride] = useState(false);

  function openReportModal() {
    if (!authed) {
      onLoginRequired();
      return;
    }
    setReportOpen(true);
  }

  function handleReportSubmitted() {
    setReportedOverride(true);
    // Patch this event's `reported` flag in the cached payloads and only mark
    // the families stale (see useFeedback) — no multi-page refetch per report.
    if (eventId !== undefined) patchCachedEvent(queryClient, eventId, { reported: true });
    for (const key of [QUERY_KEYS.feed, QUERY_KEYS.explore, QUERY_KEYS.saved, QUERY_KEYS.event]) {
      queryClient.invalidateQueries({ queryKey: [key], refetchType: 'none' });
    }
  }

  return {
    reportOpen,
    reported: baseReported || reportedOverride,
    openReportModal,
    closeReportModal: () => setReportOpen(false),
    handleReportSubmitted,
  };
}
