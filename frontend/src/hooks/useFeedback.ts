import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { type Signal } from '../constants';

interface UseFeedbackOptions {
  initialSignal?: Signal | null;
  onChange?: () => void;
}

export function useFeedback(eventId: number, opts?: UseFeedbackOptions) {
  const queryClient = useQueryClient();
  const [activeSignal, setActiveSignal] = useState<Signal | null>(opts?.initialSignal ?? null);
  const [pending, setPending] = useState(false);

  async function sendFeedback(signal: Signal) {
    if (!eventId || pending) return;
    setPending(true);
    try {
      if (signal === activeSignal) {
        await api.delete(`/feedback/${eventId}`);
        setActiveSignal(null);
      } else {
        await api.post('/feedback', { event_id: eventId, signal });
        setActiveSignal(signal);
      }
      // A feedback signal shifts every feedback-dependent read surface (Saved
      // lists, Daily 5 feed, Explore scoring, event detail), so invalidate them
      // all here — the single path every feedback action flows through.
      queryClient.invalidateQueries({ queryKey: ['saved'] });
      queryClient.invalidateQueries({ queryKey: ['feed'] });
      queryClient.invalidateQueries({ queryKey: ['explore'] });
      queryClient.invalidateQueries({ queryKey: ['event'] });
      opts?.onChange?.();
    } catch {
      // best-effort
    } finally {
      setPending(false);
    }
  }

  return { activeSignal, pending, sendFeedback };
}
