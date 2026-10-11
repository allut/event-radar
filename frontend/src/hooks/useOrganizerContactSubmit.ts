import { useState } from 'react';
import { organizerApi } from '../api/client';
import { API } from '../constants/api';
import type { LoginState } from '../constants/auth';
import { UI_STATE } from '../constants/core';
import { t } from '../i18n';
import { apiErrorMessage } from '../utils';

export interface UseOrganizerContactSubmitResult {
  message: string;
  setMessage: (v: string) => void;
  state: LoginState;
  errorMsg: string;
  submit: (e: React.FormEvent) => Promise<void>;
  reset: () => void;
}

/** Organizer-scoped sibling of useContactSubmit — name/email come from the
 * session (see routers/organizer_contact.py), so only `message` is collected
 * here. Same idle → loading → success | error shape. */
export function useOrganizerContactSubmit(locale: string): UseOrganizerContactSubmitResult {
  const [message, setMessage] = useState('');
  const [state, setState] = useState<LoginState>(UI_STATE.idle);
  const [errorMsg, setErrorMsg] = useState('');

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim()) return;
    setState(UI_STATE.loading);
    setErrorMsg('');
    try {
      await organizerApi.post(API.organizerContact, { message: message.trim() });
      setState(UI_STATE.success);
    } catch (err) {
      setErrorMsg(apiErrorMessage(err, t('generic_error', locale)));
      setState(UI_STATE.error);
    }
  }

  function reset() {
    setState(UI_STATE.idle);
    setMessage('');
    setErrorMsg('');
  }

  return { message, setMessage, state, errorMsg, submit, reset };
}
