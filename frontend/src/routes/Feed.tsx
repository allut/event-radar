import { useNavigate, Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { clearToken, getLocale } from '../lib/auth';
import { t, ti } from '../i18n';
import EventCard, { type EventData } from '../components/EventCard';
import EmptyState from '../components/EmptyState';
import PageState from '../components/PageState';
import { formatHourMinute, formatTodayDate } from '../utils';
import styles from './Feed.module.css';

interface FeedResponse {
  feed_date: string;
  events: EventData[];
  built_at: string | null;
}

export default function Feed() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const locale = getLocale();

  const { data, isLoading, isError } = useQuery({
    queryKey: ['feed'],
    queryFn: () => api.get<FeedResponse>('/feed'),
    retry: false,
  });

  function handleLogout() {
    clearToken();
    queryClient.clear();
    navigate('/login', { replace: true });
  }

  function handleFeedbackSent() {
    queryClient.invalidateQueries({ queryKey: ['feed'] });
  }

  if (isLoading) {
    return <PageState kind="loading" message={t('loading', locale)} />;
  }

  if (isError) {
    return <PageState kind="error" message={t('feed_error', locale)} />;
  }

  const events = data?.events ?? [];

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div className={styles.logoWrap}>
          <span className={styles.radar} aria-hidden>◉</span>
          <span className={styles.brand}>{t('brand', locale)}</span>
        </div>
        <div className={styles.topActions}>
          <Link to="/settings" className={styles.settingsLink}>{t('settings_link', locale)}</Link>
          <button className={styles.logoutBtn} onClick={handleLogout}>{t('sign_out', locale)}</button>
        </div>
      </header>

      <main className={styles.main}>
        <div className={styles.feedHeader}>
          <div>
            <h1 className={styles.heading}>{t('daily_five', locale)}</h1>
            <p className={styles.date}>{formatTodayDate(locale)}</p>
          </div>
          {data?.built_at && (
            <p className={styles.builtAt}>
              {ti('curated_at', locale, { time: formatHourMinute(data.built_at, locale) })}
            </p>
          )}
        </div>

        {events.length === 0 ? (
          <EmptyState
            icon="◉"
            title={t('feed_empty_title', locale)}
            message={t('feed_empty_msg', locale)}
            hint={t('feed_empty_hint', locale)}
          />
        ) : (
          <ol className={styles.list} aria-label={t('daily_five', locale)}>
            {events.map((event, i) => (
              <li key={event.id}>
                <EventCard event={event} index={i} onFeedbackSent={handleFeedbackSent} />
              </li>
            ))}
          </ol>
        )}
      </main>
    </div>
  );
}
