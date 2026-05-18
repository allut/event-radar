import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { isAuthenticated } from './lib/auth';
import { QUERY_RETRY, QUERY_STALE_TIME } from './constants';
import ErrorBoundary from './components/ErrorBoundary';
import Login from './routes/Login';
import AuthVerify from './routes/AuthVerify';
import Onboarding from './routes/Onboarding';
import Feed from './routes/Feed';
import EventDetail from './routes/EventDetail';
import Settings from './routes/Settings';
import NotFound from './routes/NotFound';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: QUERY_RETRY, staleTime: QUERY_STALE_TIME },
  },
});

function Protected({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/auth/verify" element={<AuthVerify />} />
            <Route
              path="/onboarding"
              element={<Protected><Onboarding /></Protected>}
            />
            <Route
              path="/"
              element={<Protected><Feed /></Protected>}
            />
            <Route
              path="/events/:id"
              element={<Protected><EventDetail /></Protected>}
            />
            <Route
              path="/settings"
              element={<Protected><Settings /></Protected>}
            />
            <Route path="*" element={<Protected><NotFound /></Protected>} />
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
