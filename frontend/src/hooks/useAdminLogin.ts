import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { adminApi } from '../api/client';
import { ADMIN_GENERIC_ERROR, API, ROUTES, UI_STATE, type LoginState } from '../constants';
import { setAdminSignedInHint } from '../lib/adminAuth';
import { apiErrorMessage } from '../utils';

export interface UseAdminLoginResult {
  username: string;
  setUsername: (v: string) => void;
  password: string;
  setPassword: (v: string) => void;
  totpCode: string;
  setTotpCode: (v: string) => void;
  state: LoginState;
  errorMsg: string;
  submit: (e: React.FormEvent) => Promise<void>;
}

// Password + TOTP login state machine (idle -> loading -> error, or a
// navigate-away on success — there's no "success" display state like
// MagicLinkForm's, since a correct login moves straight to the dashboard).
// Mirrors useMagicLinkRequest's shape; no i18n (the admin console is
// English-only — see ADMIN_NAV_ITEMS).
export function useAdminLogin(): UseAdminLoginResult {
  const navigate = useNavigate();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [state, setState] = useState<LoginState>(UI_STATE.idle);
  const [errorMsg, setErrorMsg] = useState('');

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password || !totpCode.trim()) return;
    setState(UI_STATE.loading);
    setErrorMsg('');
    try {
      await adminApi.post(API.adminAuthLogin, {
        username: username.trim(),
        password,
        totp_code: totpCode.trim(),
      });
      setAdminSignedInHint();
      navigate(ROUTES.adminDashboard, { replace: true });
    } catch (err) {
      setErrorMsg(apiErrorMessage(err, ADMIN_GENERIC_ERROR));
      setState(UI_STATE.error);
    }
  }

  return { username, setUsername, password, setPassword, totpCode, setTotpCode, state, errorMsg, submit };
}
