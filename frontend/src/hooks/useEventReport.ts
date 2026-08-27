import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { QUERY_KEYS, ROUTES } from '../constants';
import { useAuth } from './useAuth';
import { useLocaleNavigate } from './useLocaleNavigate';

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
 * menu (issue #128): gates the modal open on auth (redirecting signed-out
 * clicks to /login, mirroring Share's no-auth-gate exception), and on a
 * successful submit flips the local "reported" state and invalidates every
 * read surface the `reported` field appears on. */
export function useEventReport(baseReported: boolean): UseEventReportResult {
  const authed = useAuth();
  const navigate = useLocaleNavigate();
  const queryClient = useQueryClient();
  const [reportOpen, setReportOpen] = useState(false);
  const [reportedOverride, setReportedOverride] = useState(false);

  function openReportModal() {
    if (!authed) {
      navigate(ROUTES.login);
      return;
    }
    setReportOpen(true);
  }

  function handleReportSubmitted() {
    setReportedOverride(true);
    queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.feed] });
    queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.explore] });
    queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.saved] });
    queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.event] });
  }

  return {
    reportOpen,
    reported: baseReported || reportedOverride,
    openReportModal,
    closeReportModal: () => setReportOpen(false),
    handleReportSubmitted,
  };
}
