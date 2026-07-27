import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { organizerApi, ApiError } from '../../api/client';
import { getLocale, setLocale } from '../../lib/auth';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { t } from '../../i18n';
import { formatEventTime } from '../../utils';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import PageState from '../../components/PageState';
import EmptyState from '../../components/EmptyState';
import Toast from '../../components/Toast';
import { useToast } from '../../hooks/useToast';
import { QUERY_KEYS, ORGANIZER_EVENTS_PAGE_SIZE, UI_STATE } from '../../constants';
import styles from './OrganizerDashboard.module.css';

interface OrganizerEvent {
  id: number;
  slug: string;
  title: string;
  starts_at: string;
  status: string;
  needs_review: boolean;
}

interface OrganizerEventsResponse {
  events: OrganizerEvent[];
  limit: number;
  offset: number;
}

export default function OrganizerDashboard() {
  const [locale, setLocaleState] = useState(getLocale());
  const handleLogout = useOrganizerLogout();
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();

  function handleLocaleChange(code: string) {
    setLocaleState(code);
    setLocale(code);
  }

  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.organizerEvents, locale],
    queryFn: () =>
      organizerApi.get<OrganizerEventsResponse>(`/organizer/events?limit=${ORGANIZER_EVENTS_PAGE_SIZE}`),
  });

  const deleteMutation = useMutation({
    mutationFn: (eventId: number) => organizerApi.delete(`/organizer/events/${eventId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerEvents] });
      showToast(UI_STATE.success, t('organizer_delete_success', locale));
    },
    onError: (err) => {
      showToast(UI_STATE.error, err instanceof ApiError ? err.message : t('generic_error', locale));
    },
  });

  function handleDelete(eventId: number) {
    if (!window.confirm(t('organizer_delete_confirm', locale))) return;
    deleteMutation.mutate(eventId);
  }

  const events = data?.events ?? [];

  return (
    <div className={styles.page}>
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <header className={styles.masthead}>
          <h1 className={styles.heading}>{t('organizer_dashboard_title', locale)}</h1>
          <Link to="/organizer/submit" className={styles.newBtn}>{t('organizer_new_event', locale)}</Link>
        </header>

        {isLoading ? (
          <PageState kind="loading" message={t('loading', locale)} inline />
        ) : isError ? (
          <PageState kind="error" message={t('generic_error', locale)} inline />
        ) : events.length === 0 ? (
          <EmptyState
            icon="📅"
            title={t('organizer_empty_title', locale)}
            message={t('organizer_empty_msg', locale)}
          />
        ) : (
          <ul className={styles.list}>
            {events.map((event) => (
              <li key={event.id} className={styles.row}>
                <div className={styles.rowMain}>
                  <span className={styles.rowTitle}>{event.title}</span>
                  <span className={styles.rowMeta}>{formatEventTime(event.starts_at, locale)}</span>
                </div>
                <div className={styles.rowBadges}>
                  <span className={`${styles.statusBadge} ${styles[`status_${event.status}`] ?? ''}`}>
                    {t(`organizer_status_${event.status}`, locale)}
                  </span>
                  {event.needs_review && (
                    <span className={styles.reviewBadge}>{t('organizer_needs_review', locale)}</span>
                  )}
                </div>
                <div className={styles.rowActions}>
                  <Link to={`/organizer/events/${event.id}/edit`} className={styles.editBtn}>
                    {t('organizer_edit', locale)}
                  </Link>
                  <button
                    type="button"
                    className={styles.deleteBtn}
                    onClick={() => handleDelete(event.id)}
                    disabled={deleteMutation.isPending}
                  >
                    {t('organizer_delete', locale)}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>

      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}
