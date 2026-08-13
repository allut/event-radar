import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HelmetProvider } from 'react-helmet-async';
import { Analytics } from '@vercel/analytics/react';
import { SpeedInsights } from '@vercel/speed-insights/react';
import { useAuth } from './hooks/useAuth';
import { useOrganizerAuth } from './hooks/useOrganizerAuth';
import { QUERY_RETRY, QUERY_STALE_TIME, ROUTES, LOCALE_ET } from './constants';
import { maskAnalyticsUrl, localizedPath } from './utils';
import { getStoredLocale } from './lib/auth';
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
  if (!authed) return <Navigate to={ROUTES.login} replace />;
  return <>{children}</>;
}

// Mirrors Protected but on the organizer session track (useOrganizerAuth,
// redirect to /organizer/login) — the two auth tracks never share a guard.
function OrganizerProtected({ children }: { children: React.ReactNode }) {
  const authed = useOrganizerAuth();
  if (!authed) return <Navigate to={ROUTES.organizerLogin} replace />;
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
    return <Navigate to={localizedPath(location.pathname, preferred) + location.search} replace />;
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
          </BrowserRouter>
        </QueryClientProvider>
      </HelmetProvider>
    </ErrorBoundary>
  );
}
