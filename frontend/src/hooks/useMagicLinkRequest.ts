import { useState } from 'react';
import { api, ApiError } from '../api/client';
import { type LoginState } from '../constants';
import { t } from '../i18n';

/** Magic-link request state machine, shared by the Login page and the landing
 * page's email-capture forms. POSTs /auth/request-link and tracks idle →
 * loading → success | error. Centralized so the two entry points can't drift. */
export function useMagicLinkRequest(locale: string) {
  const [email, setEmail] = useState('');
  const [state, setState] = useState<LoginState>('idle');
  const [errorMsg, setErrorMsg] = useState('');

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) return;
    setState('loading');
    setErrorMsg('');
    try {
      await api.post('/auth/request-link', { email: trimmed.toLowerCase(), locale });
      setState('success');
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : t('generic_error', locale));
      setState('error');
    }
  }

  function reset() {
    setState('idle');
    setEmail('');
    setErrorMsg('');
  }

  return { email, setEmail, state, errorMsg, submit, reset };
}
