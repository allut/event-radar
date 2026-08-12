import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Analytics } from '@vercel/analytics/react';
import { SpeedInsights } from '@vercel/speed-insights/react';
import { useAuth } from './hooks/useAuth';
import { useOrganizerAuth } from './hooks/useOrganizerAuth';
import { QUERY_RETRY, QUERY_STALE_TIME, ROUTES } from './constants';
import { maskAnalyticsUrl } from './utils';
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

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route path={ROUTES.login} element={<Login />} />
            <Route path={ROUTES.authVerify} element={<AuthVerify />} />
            <Route
              path={ROUTES.onboarding}
              element={<Protected><Onboarding /></Protected>}
            />
            <Route
              path={ROUTES.home}
              element={<Home />}
            />
            <Route
              path={ROUTES.explore}
              element={<Protected><Explore /></Protected>}
            />
            <Route
              path={ROUTES.saved}
              element={<Protected><SavedEvents /></Protected>}
            />
            <Route
              path={ROUTES.eventDetailPattern}
              element={<EventDetail />}
            />
            <Route
              path={ROUTES.settings}
              element={<Protected><Settings /></Protected>}
            />
            <Route path={ROUTES.unsubscribe} element={<Unsubscribe />} />
            <Route path={ROUTES.privacy} element={<Privacy />} />
            <Route path={ROUTES.terms} element={<Terms />} />
            <Route path={ROUTES.contact} element={<Contact />} />
            <Route path={ROUTES.organizerLogin} element={<OrganizerLogin />} />
            <Route path={ROUTES.organizerVerify} element={<OrganizerVerify />} />
            <Route
              path={ROUTES.organizerDashboard}
              element={<OrganizerProtected><OrganizerDashboard /></OrganizerProtected>}
            />
            <Route
              path={ROUTES.organizerSubmit}
              element={<OrganizerProtected><EventSubmit /></OrganizerProtected>}
            />
            <Route
              path={ROUTES.organizerEventEditPattern}
              element={<OrganizerProtected><EventSubmit /></OrganizerProtected>}
            />
            <Route path="*" element={<Protected><NotFound /></Protected>} />
          </Routes>
          <Footer />
          <Analytics beforeSend={(e) => ({ ...e, url: maskAnalyticsUrl(e.url) })} />
          <SpeedInsights beforeSend={(e) => ({ ...e, url: maskAnalyticsUrl(e.url) })} />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
