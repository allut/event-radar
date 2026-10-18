import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HelmetProvider } from 'react-helmet-async';
import { useAuth } from './hooks/useAuth';
import { useOrganizerAuth } from './hooks/useOrganizerAuth';
import { useLocalePath } from './hooks/useLocalePath';
import { QUERY_RETRY, QUERY_STALE_TIME } from './constants/api';
import { LOCALE_ET } from './constants/core';
import { ROUTES } from './constants/routes';
import { localizedTo } from './utils';
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
import ConsentOff from './routes/ConsentOff';
import Privacy from './routes/Privacy';
import Terms from './routes/Terms';
import Ranking from './routes/Ranking';
import OrganizerTerms from './routes/OrganizerTerms';
import Contact from './routes/Contact';
import Faq from './routes/Faq';
import OrganizerLogin from './routes/OrganizerLogin';
import OrganizerVerify from './routes/OrganizerVerify';
import OrganizerClaimVerify from './routes/OrganizerClaimVerify';
import ClaimPending from './routes/ClaimPending';
import ClaimEventEdit from './routes/ClaimEventEdit';
import ClaimEvents from './routes/ClaimEvents';
import OrganizerDashboard from './routes/OrganizerDashboard';
import OrganizerClaims from './routes/OrganizerClaims';
import OrganizerSettings from './routes/OrganizerSettings';
import OrganizerContact from './routes/OrganizerContact';
import OrganizerPromotions from './routes/OrganizerPromotions';
import OrganizerPromotionRequest from './routes/OrganizerPromotionRequest';
import OrganizerPromotionSuccess from './routes/OrganizerPromotionSuccess';
import EventSubmit from './routes/EventSubmit';
import NotFound from './routes/NotFound';
import Footer from './components/Footer';

// The admin console's own React.lazy boundary (issue #154) — its whole route
// tree (AdminApp) lives in a separate chunk, never downloaded by a signed-out
// public-route visit. Registered below, entirely outside ROUTE_DEFS/the
// locale-prefix loop.
const AdminApp = lazy(() => import('./routes/AdminApp'));

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

// Bare-path locale redirect, applied only to "standard" routes (everything
// except Home/Explore/EventDetail — see NO_REDIRECT below). If the visitor has an
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

// The public Footer is suppressed on /admin/* — the admin console has its
// own minimal chrome (AdminShell), not the public app's (issue #154).
function ConditionalFooter() {
  const { pathname } = useLocation();
  if (pathname.startsWith(ROUTES.adminBase)) return null;
  return <Footer />;
}

function localePrefixedPattern(path: string): string {
  return path === ROUTES.home ? '/:locale' : `/:locale${path}`;
}

interface RouteDef {
  path: string;
  element: React.ReactNode;
  // Home, Explore, EventDetail and Faq are the four public SEO routes (issue
  // #236 added Explore, #491 Faq): their bare path always renders Estonian and
  // never redirects (crawler/prerender stability), regardless of any stored
  // locale preference.
  noRedirect?: boolean;
}

const ROUTE_DEFS: RouteDef[] = [
  { path: ROUTES.login, element: <Login /> },
  { path: ROUTES.authVerify, element: <AuthVerify /> },
  { path: ROUTES.onboarding, element: <Protected><Onboarding /></Protected> },
  { path: ROUTES.home, element: <Home />, noRedirect: true },
  { path: ROUTES.explore, element: <Explore />, noRedirect: true },
  { path: ROUTES.saved, element: <Protected><SavedEvents /></Protected> },
  { path: ROUTES.eventDetailPattern, element: <EventDetail />, noRedirect: true },
  { path: ROUTES.settings, element: <Protected><Settings /></Protected> },
  { path: ROUTES.unsubscribe, element: <Unsubscribe /> },
  { path: ROUTES.consentOff, element: <ConsentOff /> },
  { path: ROUTES.privacy, element: <Privacy /> },
  { path: ROUTES.terms, element: <Terms /> },
  { path: ROUTES.ranking, element: <Ranking /> },
  { path: ROUTES.organizerTerms, element: <OrganizerTerms /> },
  { path: ROUTES.contact, element: <Contact /> },
  { path: ROUTES.faq, element: <Faq />, noRedirect: true },
  { path: ROUTES.organizerLogin, element: <OrganizerLogin /> },
  { path: ROUTES.organizerVerify, element: <OrganizerVerify /> },
  { path: ROUTES.organizerClaimVerify, element: <OrganizerClaimVerify /> },
  { path: ROUTES.organizerClaimPendingPattern, element: <OrganizerProtected><ClaimPending /></OrganizerProtected> },
  { path: ROUTES.organizerClaimEditPattern, element: <OrganizerProtected><ClaimEventEdit /></OrganizerProtected> },
  { path: ROUTES.organizerClaimEventsPattern, element: <OrganizerProtected><ClaimEvents /></OrganizerProtected> },
  { path: ROUTES.organizerDashboard, element: <OrganizerProtected><OrganizerDashboard /></OrganizerProtected> },
  { path: ROUTES.organizerClaims, element: <OrganizerProtected><OrganizerClaims /></OrganizerProtected> },
  { path: ROUTES.organizerSettings, element: <OrganizerProtected><OrganizerSettings /></OrganizerProtected> },
  { path: ROUTES.organizerContact, element: <OrganizerProtected><OrganizerContact /></OrganizerProtected> },
  { path: ROUTES.organizerPromotions, element: <OrganizerProtected><OrganizerPromotions /></OrganizerProtected> },
  { path: ROUTES.organizerPromotionRequest, element: <OrganizerProtected><OrganizerPromotionRequest /></OrganizerProtected> },
  { path: ROUTES.organizerPromotionSuccess, element: <OrganizerProtected><OrganizerPromotionSuccess /></OrganizerProtected> },
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
              {/* Three registrations, all pointing at the same lazy AdminApp
                  chunk — see AdminApp.tsx's screenFor comment for why a
                  single "/admin/*" splat isn't enough: react-router scores a
                  matched static segment above a splat, so "/:locale/login"
                  and "/:locale/events/:id" (both registered above from
                  ROUTE_DEFS) would otherwise outrank a bare "/admin/*" for
                  the literal paths "/admin/login" and "/admin/events/:id".
                  These two extra entries add enough static segments to win
                  outright; every other /admin/... path has no such
                  same-shape collision, so the plain splat still covers them. */}
              <Route path={ROUTES.adminLogin} element={<Suspense fallback={null}><AdminApp /></Suspense>} />
              <Route path={ROUTES.adminEventsSplat} element={<Suspense fallback={null}><AdminApp /></Suspense>} />
              <Route path={ROUTES.adminSplat} element={<Suspense fallback={null}><AdminApp /></Suspense>} />
              <Route path="*" element={<Protected><NotFound /></Protected>} />
              <Route path="/:locale/*" element={<Protected><NotFound /></Protected>} />
            </Routes>
            <ConditionalFooter />
          </BrowserRouter>
        </QueryClientProvider>
      </HelmetProvider>
    </ErrorBoundary>
  );
}
