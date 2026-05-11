import { useState } from 'react';
import { api } from '../api/client';
import { type Signal } from '../constants';

export function useFeedback(eventId: number, onSent?: () => void) {
  const [activeSignal, setActiveSignal] = useState<Signal | null>(null);
  const [pending, setPending] = useState(false);

  async function sendFeedback(signal: Signal) {
    if (!eventId || pending || activeSignal === signal) return;
    setPending(true);
    try {
      await api.post('/feedback', { event_id: eventId, signal });
      setActiveSignal(signal);
      onSent?.();
    } catch {
      // best-effort
    } finally {
      setPending(false);
    }
  }

  return { activeSignal, pending, sendFeedback };
}
