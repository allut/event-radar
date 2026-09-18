import { setSignedInHint } from './auth';
import { setOrganizerSignedInHint } from './organizerAuth';
import {
  GOOGLE_SIGNIN_RESULT_PARAM,
  GOOGLE_SIGNIN_RESULT_TRACK_ORGANIZER,
  GOOGLE_SIGNIN_RESULT_TRACK_USER,
} from '../constants';

// Google sign-in is a server-side redirect: no app JS runs between the
// backend setting the session cookie and the browser landing on the SPA, so
// the localStorage signed-in hint the route guards read (AuthVerify.tsx/
// OrganizerVerify.tsx's magic-link routes set it in-page) never gets written.
// This runs synchronously before the router's first render — see main.tsx —
// so the guard's first read already sees the hint. No theme sync here (ADR
// 0003) — the browser's theme override is never read from or written to an
// account, so sign-in has nothing to reconcile.
export function consumeGoogleSignInLanding(): void {
  const params = new URLSearchParams(window.location.search);
  const track = params.get(GOOGLE_SIGNIN_RESULT_PARAM);
  if (track !== GOOGLE_SIGNIN_RESULT_TRACK_USER && track !== GOOGLE_SIGNIN_RESULT_TRACK_ORGANIZER) {
    return;
  }

  params.delete(GOOGLE_SIGNIN_RESULT_PARAM);
  const query = params.toString();
  window.history.replaceState(
    {},
    '',
    `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
  );

  if (track === GOOGLE_SIGNIN_RESULT_TRACK_ORGANIZER) {
    setOrganizerSignedInHint();
    return;
  }

  setSignedInHint();
}
