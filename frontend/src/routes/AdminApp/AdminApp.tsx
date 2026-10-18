import type { ReactNode } from 'react';
import { Helmet } from 'react-helmet-async';
import { Navigate, useLocation } from 'react-router-dom';
import { ROUTES } from '../../constants/routes';
import { ROBOTS_NOINDEX } from '../../constants/seo';
import { useAdminAuth } from '../../hooks/useAdminAuth';
import AdminShell from '../../components/AdminShell';
import AdminLogin from '../AdminLogin';
import AdminDashboard from '../AdminDashboard';
import AdminReports from '../AdminReports';
import AdminSubmissions from '../AdminSubmissions';
import AdminClaims from '../AdminClaims';
import AdminEventDetail from '../AdminEventDetail';
import AdminPipeline from '../AdminPipeline';
import AdminDedup from '../AdminDedup';
import AdminPromotions from '../AdminPromotions';

// Mirrors App.tsx's Protected/OrganizerProtected — a third guard on the
// admin session track (useAdminAuth, redirect to /admin/login).
function AdminProtected({ children }: { children: ReactNode }) {
  const authed = useAdminAuth();
  if (!authed) return <Navigate to={ROUTES.adminLogin} replace />;
  return <>{children}</>;
}

// AdminApp dispatches on the real pathname itself rather than a nested
// react-router-dom <Routes> tree. A nested <Routes> only gets a relative
// remainder to match against when its ancestor <Route> matched via a
// trailing "/*" — and App.tsx cannot mount this whole track behind one such
// splat, because a bare "/admin/*" splat scores lower than some of the
// app's own "/:locale/<page>" patterns for a same-shape path (e.g.
// "/:locale/login" outranks "/admin/*" for the literal path "/admin/login",
// since react-router scores a matched static segment higher than a splat).
// App.tsx instead registers a few literal /admin/... paths (see its own
// comment) that outrank those collisions outright, all pointing at this one
// component — so the dispatch has to happen here, in plain code, rather
// than through react-router's own nested route matching.
function screenFor(pathname: string): ReactNode | null {
  if (pathname === ROUTES.adminDashboard) return <AdminDashboard />;
  if (pathname === ROUTES.adminReports) return <AdminReports />;
  if (pathname === ROUTES.adminSubmissions) return <AdminSubmissions />;
  if (pathname === ROUTES.adminClaims) return <AdminClaims />;
  if (pathname === ROUTES.adminPipeline) return <AdminPipeline />;
  if (pathname === ROUTES.adminDedup) return <AdminDedup />;
  if (pathname === ROUTES.adminPromotions) return <AdminPromotions />;
  if (
    pathname.startsWith(ROUTES.adminEventDetailPrefix) &&
    pathname.length > ROUTES.adminEventDetailPrefix.length
  ) {
    return <AdminEventDetail eventId={pathname.slice(ROUTES.adminEventDetailPrefix.length)} />;
  }
  return null;
}

// The whole /admin/* track's single React.lazy boundary (App.tsx dynamic-
// imports this module) — everything under it, including AdminShell and every
// screen, lands in one separate chunk, never in the main bundle a signed-out
// public-route visit downloads. Registered entirely outside App.tsx's
// ROUTE_DEFS/locale-prefix loop: no i18n, no locale prefix, no in-app link —
// entry is typed-URL/bookmark only (issue #154).
function NoindexMeta() {
  return <Helmet><meta name="robots" content={ROBOTS_NOINDEX} /></Helmet>;
}

export default function AdminApp() {
  const { pathname } = useLocation();

  if (pathname === ROUTES.adminLogin) {
    return (
      <>
        <NoindexMeta />
        <AdminLogin />
      </>
    );
  }

  const screen = screenFor(pathname);
  return (
    <>
      <NoindexMeta />
      <AdminProtected>
        {screen ? <AdminShell>{screen}</AdminShell> : <Navigate to={ROUTES.adminDashboard} replace />}
      </AdminProtected>
    </>
  );
}
