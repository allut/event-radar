import { useState } from 'react';
import { api, ApiError } from '../api/client';
import { UI_STATE, type LoginState } from '../constants';
import { t } from '../i18n';

/** Contact-form submit state machine, mirroring useMagicLinkRequest's
 * idle → loading → success | error shape. `website` is a honeypot field the
 * backend expects to stay blank — never rendered visibly. */
export function useContactSubmit(locale: string) {
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
      await api.post('/contact', { name: name.trim(), email: email.trim(), message: message.trim(), website });
      setState(UI_STATE.success);
    } catch (err) {
      setErrorMsg(err instanceof ApiError ? err.message : t('generic_error', locale));
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
