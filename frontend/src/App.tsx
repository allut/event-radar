import { useEffect } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HelmetProvider } from 'react-helmet-async';
import { Analytics } from '@vercel/analytics/react';
import { SpeedInsights } from '@vercel/speed-insights/react';
import { useAuth } from './hooks/useAuth';
import { useOrganizerAuth } from './hooks/useOrganizerAuth';
import { useLocalePath } from './hooks/useLocalePath';
import { QUERY_RETRY, QUERY_STALE_TIME, ROUTES, LOCALE_ET } from './constants';
import { maskAnalyticsUrl, localizedTo } from './utils';
import { getStoredLocale } from './lib/auth';
import { initGtag, trackPageview } from './lib/gtag';
import ErrorBoundary from './components/ErrorBoundary';
import Landing from './routes/Landing';
import Login from './routes/Login';
import AuthVerify from './routes/AuthVerify';
import Onboarding from './routes/Onboarding';
import Feed from './routes/Feed';
import Explore from './routes/Explore';
import SavedEvents from './routes/SavedEvents';
import EventDetail from './routes/EventDetail';
import Settings from './routes/Settings';
import Unsubscribe from './routes/Unsubscribe';
import Privacy from './routes/Privacy';
import Terms from './routes/Terms';
import Contact from './routes/Contact';
import OrganizerLogin from './routes/OrganizerLogin';
import OrganizerVerify from './routes/OrganizerVerify';
import OrganizerDashboard from './routes/OrganizerDashboard';
import EventSubmit from './routes/EventSubmit';
import NotFound from './routes/NotFound';
import Footer from './components/Footer';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: QUERY_RETRY, staleTime: QUERY_STALE_TIME },
  },
});

function Protected({ children }: { children: React.ReactNode }) {
  const authed = useAuth();
  const localePath = useLocalePath();
  if (!authed) return <Navigate to={localePath(ROUTES.login)} replace />;
  return <>{children}</>;
}

// Mirrors Protected but on the organizer session track (useOrganizerAuth,
// redirect to /organizer/login) — the two auth tracks never share a guard.
function OrganizerProtected({ children }: { children: React.ReactNode }) {
  const authed = useOrganizerAuth();
  const localePath = useLocalePath();
  if (!authed) return <Navigate to={localePath(ROUTES.organizerLogin)} replace />;
  return <>{children}</>;
}

// Root: the marketing Landing for logged-out visitors, the Feed for signed-in
// users. Subscribes to auth state via useAuth() (backed by lib/auth's
// subscribe/emit store) rather than reading localStorage once at render —
// signing out while already on "/" doesn't change the route, so a plain
// isAuthenticated() read here would never re-run and would strand a
// just-signed-out user on a stale Feed. Also covers magic-link verify
// redirecting a freshly-authenticated user here.
function Home() {
  const authed = useAuth();
  return authed ? <Feed /> : <Landing />;
}

// GA4 pageview tracking — a route-change effect rather than gtag.js's own
// automatic pageview, so every reported path goes through maskAnalyticsUrl
// first (the /auth/verify magic-link token or an /explore free-text search
// must never reach Google in a query string). initGtag() itself no-ops with
// no VITE_GA_MEASUREMENT_ID configured or under Playwright's prerender render
// pass (see lib/gtag.ts's isPrerenderRender), so this is safe to mount always.
//
// The tracking effect is deferred a tick rather than firing synchronously on
// every pathname change: BareLocaleGate below client-side-redirects a bare
// URL to a stored non-Estonian locale's prefixed equivalent, which is a real
// history change, not just a re-render — without the defer, a redirected
// visit would fire one pageview for the pre-redirect bare path and a second
// for the post-redirect prefixed path, double-counting one visit. Deferring
// lets the redirect's own pathname change land first and cancel this timer
// (the cleanup below) before it ever fires, so only the settled path is sent.
function GoogleAnalytics() {
  const location = useLocation();
  useEffect(() => {
    initGtag(import.meta.env.VITE_GA_MEASUREMENT_ID);
  }, []);
  useEffect(() => {
    const id = window.setTimeout(() => trackPageview(maskAnalyticsUrl(location.pathname)), 0);
    return () => window.clearTimeout(id);
  }, [location.pathname]);
  return null;
}

// Bare-path locale redirect, applied only to "standard" routes (everything
// except Home/EventDetail — see NO_REDIRECT below). If the visitor has an
// explicit, stored non-Estonian locale preference, a bare URL (no `:locale`
// segment matched) redirects client-side to that preference's prefixed
// equivalent. No Accept-Language sniffing: a first-time visitor with no
// stored preference (getStoredLocale() === null) falls through to Estonian,
// same as an explicit "et" preference — neither redirects.
function BareLocaleGate({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const preferred = getStoredLocale() ?? LOCALE_ET;
  if (preferred !== LOCALE_ET) {
    return <Navigate to={localizedTo(location.pathname + location.search + location.hash, preferred)} replace />;
  }
  return <>{children}</>;
}

function localePrefixedPattern(path: string): string {
  return path === ROUTES.home ? '/:locale' : `/:locale${path}`;
}

interface RouteDef {
  path: string;
  element: React.ReactNode;
  // Home and EventDetail are the two public SEO routes: their bare path
  // always renders Estonian and never redirects (crawler/prerender
  // stability), regardless of any stored locale preference.
  noRedirect?: boolean;
}

const ROUTE_DEFS: RouteDef[] = [
  { path: ROUTES.login, element: <Login /> },
  { path: ROUTES.authVerify, element: <AuthVerify /> },
  { path: ROUTES.onboarding, element: <Protected><Onboarding /></Protected> },
  { path: ROUTES.home, element: <Home />, noRedirect: true },
  { path: ROUTES.explore, element: <Protected><Explore /></Protected> },
  { path: ROUTES.saved, element: <Protected><SavedEvents /></Protected> },
  { path: ROUTES.eventDetailPattern, element: <EventDetail />, noRedirect: true },
  { path: ROUTES.settings, element: <Protected><Settings /></Protected> },
  { path: ROUTES.unsubscribe, element: <Unsubscribe /> },
  { path: ROUTES.privacy, element: <Privacy /> },
  { path: ROUTES.terms, element: <Terms /> },
  { path: ROUTES.contact, element: <Contact /> },
  { path: ROUTES.organizerLogin, element: <OrganizerLogin /> },
  { path: ROUTES.organizerVerify, element: <OrganizerVerify /> },
  { path: ROUTES.organizerDashboard, element: <OrganizerProtected><OrganizerDashboard /></OrganizerProtected> },
  { path: ROUTES.organizerSubmit, element: <OrganizerProtected><EventSubmit /></OrganizerProtected> },
  { path: ROUTES.organizerEventEditPattern, element: <OrganizerProtected><EventSubmit /></OrganizerProtected> },
];

export default function App() {
  return (
    <ErrorBoundary>
      <HelmetProvider>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <Routes>
              {ROUTE_DEFS.map(({ path, element, noRedirect }) => (
                <Route
                  key={path}
                  path={path}
                  element={noRedirect ? element : <BareLocaleGate>{element}</BareLocaleGate>}
                />
              ))}
              {ROUTE_DEFS.map(({ path, element }) => (
                <Route key={`loc:${path}`} path={localePrefixedPattern(path)} element={element} />
              ))}
              <Route path="*" element={<Protected><NotFound /></Protected>} />
              <Route path="/:locale/*" element={<Protected><NotFound /></Protected>} />
            </Routes>
            <Footer />
            <Analytics beforeSend={(e) => ({ ...e, url: maskAnalyticsUrl(e.url) })} />
            <SpeedInsights beforeSend={(e) => ({ ...e, url: maskAnalyticsUrl(e.url) })} />
            <GoogleAnalytics />
          </BrowserRouter>
        </QueryClientProvider>
      </HelmetProvider>
    </ErrorBoundary>
  );
}
