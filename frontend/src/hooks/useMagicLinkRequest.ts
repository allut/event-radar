import { useState } from 'react';
import { api, organizerApi } from '../api/client';
import { API } from '../constants/api';
import type { LoginState } from '../constants/auth';
import { UI_STATE } from '../constants/core';
import { t } from '../i18n';
import { apiErrorMessage } from '../utils';

export interface UseMagicLinkRequestResult {
  email: string;
  setEmail: (v: string) => void;
  state: LoginState;
  errorMsg: string;
  submit: (e: React.FormEvent) => Promise<void>;
  reset: () => void;
}

/** Magic-link request state machine, shared by the Login page, the landing
 * page's email-capture forms, OrganizerLogin (via `requestPath` +
 * `organizer`), and the claim-discovery CTA (via `extraBody`, which carries
 * the claim intent — event_id — into the request body alongside email/locale;
 * see app/routers/organizer_claims.py::request_claim_link). POSTs
 * `requestPath` (through the organizer-scoped client when `organizer` is
 * set) and tracks idle → loading → success | error. Centralized so the entry
 * points can't drift. */
export function useMagicLinkRequest(locale: string, requestPath: string = API.authRequestLink, organizer = false, extraBody?: Record<string, unknown>): UseMagicLinkRequestResult {
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
      const body = { email: trimmed.toLowerCase(), locale, ...extraBody };
      if (organizer) {
        await organizerApi.post(requestPath, body);
      } else {
        await api.post(requestPath, body);
      }
      setState(UI_STATE.success);
    } catch (err) {
      setErrorMsg(apiErrorMessage(err, t('generic_error', locale)));
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
