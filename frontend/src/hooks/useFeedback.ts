import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { API, type Signal, QUERY_KEYS } from '../constants';

interface UseFeedbackOptions {
  initialSignal?: Signal | null;
  onChange?: () => void;
}

export interface UseFeedbackResult {
  activeSignal: Signal | null;
  pending: boolean;
  sendFeedback: (signal: Signal) => Promise<void>;
}

export function useFeedback(eventId: number, opts?: UseFeedbackOptions): UseFeedbackResult {
  const queryClient = useQueryClient();
  const [activeSignal, setActiveSignal] = useState<Signal | null>(opts?.initialSignal ?? null);
  const [pending, setPending] = useState(false);

  async function sendFeedback(signal: Signal) {
    if (!eventId || pending) return;
    setPending(true);
    try {
      if (signal === activeSignal) {
        await api.delete(API.feedbackEvent(eventId));
        setActiveSignal(null);
      } else {
        await api.post(API.feedback, { event_id: eventId, signal });
        setActiveSignal(signal);
      }
      // A feedback signal shifts every feedback-dependent read surface (Saved
      // lists, Daily 5 feed, Explore scoring, event detail), so invalidate them
      // all here — the single path every feedback action flows through.
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.saved] });
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.feed] });
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.explore] });
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.event] });
      opts?.onChange?.();
    } catch {
      // best-effort
    } finally {
      setPending(false);
    }
  }

  return { activeSignal, pending, sendFeedback };
}
