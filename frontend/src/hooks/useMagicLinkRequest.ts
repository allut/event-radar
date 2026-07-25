import { useState } from 'react';
import { api, ApiError } from '../api/client';
import { UI_STATE, type LoginState } from '../constants';
import { t } from '../i18n';

/** Magic-link request state machine, shared by the Login page and the landing
 * page's email-capture forms. POSTs /auth/request-link and tracks idle →
 * loading → success | error. Centralized so the two entry points can't drift. */
export function useMagicLinkRequest(locale: string) {
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
      await api.post('/auth/request-link', { email: trimmed.toLowerCase(), locale });
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
