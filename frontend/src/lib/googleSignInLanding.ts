import { api, organizerApi } from '../api/client';
import { setSignedInHint } from './auth';
import { setOrganizerSignedInHint } from './organizerAuth';
import { syncAccountTheme } from './theme';
import {
  API,
  GOOGLE_SIGNIN_RESULT_PARAM,
  GOOGLE_SIGNIN_RESULT_TRACK_ORGANIZER,
  GOOGLE_SIGNIN_RESULT_TRACK_USER,
} from '../constants';

interface MeThemeResponse {
  theme_preference: 'light' | 'dark' | null;
}

// Google sign-in is a server-side redirect: no app JS runs between the
// backend setting the session cookie and the browser landing on the SPA, so
// the localStorage signed-in hint the route guards read (AuthVerify.tsx/
// OrganizerVerify.tsx's magic-link routes set it in-page) never gets written.
// This runs synchronously before the router's first render — see main.tsx —
// so the guard's first read already sees the hint. Mirrors the verify
// routes' post-sign-in theme sync; a 401 there correctly trips client.ts's
// expiry redirect, so failures are swallowed rather than surfaced here.
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
    void organizerApi
      .get<MeThemeResponse>(API.organizerProfile)
      .then((profile) =>
        syncAccountTheme(profile.theme_preference, (theme) =>
          organizerApi.patch(API.organizerProfile, { theme_preference: theme }),
        ),
      )
      .catch(() => {
        // Non-fatal — organizer sign-in already succeeded.
      });
    return;
  }

  setSignedInHint();
  void api
    .get<MeThemeResponse>(API.authMe)
    .then((me) =>
      syncAccountTheme(me.theme_preference, (theme) => api.patch(API.me, { theme_preference: theme })),
    )
    .catch(() => {
      // Non-fatal — user sign-in already succeeded.
    });
}
