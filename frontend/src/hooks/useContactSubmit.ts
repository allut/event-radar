import { useState } from 'react';
import { api } from '../api/client';
import { API } from '../constants/api';
import type { LoginState } from '../constants/auth';
import { UI_STATE } from '../constants/core';
import { t } from '../i18n';
import { apiErrorMessage } from '../utils';

export interface UseContactSubmitResult {
  name: string;
  setName: (v: string) => void;
  email: string;
  setEmail: (v: string) => void;
  message: string;
  setMessage: (v: string) => void;
  website: string;
  setWebsite: (v: string) => void;
  state: LoginState;
  errorMsg: string;
  submit: (e: React.FormEvent) => Promise<void>;
  reset: () => void;
}

/** Contact-form submit state machine, mirroring useMagicLinkRequest's
 * idle → loading → success | error shape. `website` is a honeypot field the
 * backend expects to stay blank — never rendered visibly. */
export function useContactSubmit(locale: string): UseContactSubmitResult {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [website, setWebsite] = useState('');
  const [state, setState] = useState<LoginState>(UI_STATE.idle);
  const [errorMsg, setErrorMsg] = useState('');

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !email.trim() || !message.trim()) return;
    setState(UI_STATE.loading);
    setErrorMsg('');
    try {
      await api.post(API.contact, { name: name.trim(), email: email.trim(), message: message.trim(), website });
      setState(UI_STATE.success);
    } catch (err) {
      setErrorMsg(apiErrorMessage(err, t('generic_error', locale)));
      setState(UI_STATE.error);
    }
  }

  function reset() {
    setState(UI_STATE.idle);
    setName('');
    setEmail('');
    setMessage('');
    setErrorMsg('');
  }

  return {
    name, setName,
    email, setEmail,
    message, setMessage,
    website, setWebsite,
    state, errorMsg, submit, reset,
  };
}
