import { useState } from 'react';
import { api, organizerApi, ApiError } from '../api/client';
import { UI_STATE, type LoginState } from '../constants';
import { t } from '../i18n';

/** Magic-link request state machine, shared by the Login page, the landing
 * page's email-capture forms, and OrganizerLogin (via `requestPath` +
 * `organizer`). POSTs `requestPath` (through the organizer-scoped client when
 * `organizer` is set) and tracks idle → loading → success | error. Centralized
 * so the entry points can't drift. */
export function useMagicLinkRequest(locale: string, requestPath: string = '/auth/request-link', organizer = false) {
  const [email, setEmail] = useState('');
  const [state, setState] = useState<LoginState>(UI_STATE.idle);
  const [errorMsg, setErrorMsg] = useState('');

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) return;
    setState(UI_STATE.loading);
    setErrorMsg('');
    try {
      const body = { email: trimmed.toLowerCase(), locale };
      if (organizer) {
        await organizerApi.post(requestPath, body);
      } else {
        await api.post(requestPath, body);
      }
      setState(UI_STATE.success);
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : t('generic_error', locale));
      setState(UI_STATE.error);
    }
  }

  function reset() {
    setState(UI_STATE.idle);
    setEmail('');
    setErrorMsg('');
  }

  return { email, setEmail, state, errorMsg, submit, reset };
}
