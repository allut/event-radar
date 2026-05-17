import { useNavigate, Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { clearToken, getLocale } from '../lib/auth';
import { toLocaleCode } from '../constants';
import { t, ti } from '../i18n';
import EventCard, { type EventData } from '../components/EventCard';
import { formatTodayDate } from '../utils';
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
    return (
      <div className={styles.centered}>
        <span className={styles.spinner} aria-label={t('loading', locale)} />
      </div>
    );
  }

  if (isError) {
    return (
      <div className={styles.centered}>
        <p className={styles.errorMsg}>{t('feed_error', locale)}</p>
      </div>
    );
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
              {ti('curated_at', locale, {
                time: new Date(data.built_at).toLocaleTimeString(
                  toLocaleCode(locale),
                  { hour: '2-digit', minute: '2-digit' }
                ),
              })}
            </p>
          )}
        </div>

        {events.length === 0 ? (
          <div className={styles.empty}>
            <div className={styles.emptyIcon} aria-hidden>◉</div>
            <h2 className={styles.emptyTitle}>{t('feed_empty_title', locale)}</h2>
            <p className={styles.emptyMsg}>{t('feed_empty_msg', locale)}</p>
            <p className={styles.emptyHint}>{t('feed_empty_hint', locale)}</p>
          </div>
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
