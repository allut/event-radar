import { useState } from 'react';
import { SAVE_MSG_CLEAR_DELAY_MS, UI_STATE, TOAST_IDLE, type ToastState } from '../constants/core';

export interface UseToastResult {
  toast: ToastState;
  showToast: (status: typeof UI_STATE.success | typeof UI_STATE.error, message: string) => void;
}

/** Local toast state with auto-clear, shared by any page that needs a
 * transient success/error confirmation (mirrors the pattern Settings used
 * inline before it was promoted here). */
export function useToast(): UseToastResult {
  const [toast, setToast] = useState<ToastState>(TOAST_IDLE);

  function showToast(status: typeof UI_STATE.success | typeof UI_STATE.error, message: string) {
    setToast({ status, message });
    if (status === UI_STATE.success) {
      setTimeout(() => setToast(TOAST_IDLE), SAVE_MSG_CLEAR_DELAY_MS);
    }
  }

  return { toast, showToast };
}
