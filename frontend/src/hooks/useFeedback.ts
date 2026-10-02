import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { API, type Signal, QUERY_KEYS } from '../constants';
import { patchCachedEvent } from '../utils';

interface UseFeedbackOptions {
  initialSignal?: Signal | null;
  onChange?: () => void;
}

export interface UseFeedbackResult {
  activeSignal: Signal | null;
  pending: boolean;
  sendFeedback: (signal: Signal) => Promise<void>;
}

export function useFeedback(eventId: number | undefined, opts?: UseFeedbackOptions): UseFeedbackResult {
  const queryClient = useQueryClient();
  const [activeSignal, setActiveSignal] = useState<Signal | null>(opts?.initialSignal ?? null);
  const [pending, setPending] = useState(false);

  async function sendFeedback(signal: Signal) {
    if (eventId === undefined || pending) return;
    setPending(true);
    try {
      let nextSignal: Signal | null;
      if (signal === activeSignal) {
        await api.delete(API.feedbackEvent(eventId));
        nextSignal = null;
      } else {
        await api.post(API.feedback, { event_id: eventId, signal });
        nextSignal = signal;
      }
      setActiveSignal(nextSignal);
      // A feedback signal shifts every feedback-dependent read surface — the
      // single path every feedback action flows through. Saved lists change
      // membership with the signal, so the mounted one refetches. Feed is one
      // small page, so it refetches too. Explore / event detail only need this
      // event's `my_signal` patched in place and are just marked stale
      // (refetchType 'none') so the next mount re-scores — an active Explore
      // would otherwise refetch every loaded page on each like. A dislike is a
      // hard exclude server-side, so it does refetch Explore to drop the card.
      patchCachedEvent(queryClient, eventId, { my_signal: nextSignal });
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.saved] });
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.feed] });
      queryClient.invalidateQueries({
        queryKey: [QUERY_KEYS.explore],
        refetchType: nextSignal === 'dislike' ? 'active' : 'none',
      });
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.event], refetchType: 'none' });
      opts?.onChange?.();
    } catch {
      // best-effort
    } finally {
      setPending(false);
    }
  }

  return { activeSignal, pending, sendFeedback };
}
