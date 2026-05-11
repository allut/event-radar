import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { clearToken, getLocale } from '../lib/auth';
import { toLocaleCode } from '../constants';
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
        <span className={styles.spinner} aria-label="Loading feed…" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className={styles.centered}>
        <p className={styles.errorMsg}>Failed to load your feed. Please refresh.</p>
      </div>
    );
  }

  const events = data?.events ?? [];

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <div className={styles.logoWrap}>
          <span className={styles.radar} aria-hidden>◉</span>
          <span className={styles.brand}>Event Radar</span>
        </div>
        <button className={styles.logoutBtn} onClick={handleLogout}>Sign out</button>
      </header>

      <main className={styles.main}>
        <div className={styles.feedHeader}>
          <div>
            <h1 className={styles.heading}>Your Daily Five</h1>
            <p className={styles.date}>{formatTodayDate(locale)}</p>
          </div>
          {data?.built_at && (
            <p className={styles.builtAt}>
              Curated at{' '}
              {new Date(data.built_at).toLocaleTimeString(
                toLocaleCode(locale),
                { hour: '2-digit', minute: '2-digit' }
              )}
            </p>
          )}
        </div>

        {events.length === 0 ? (
          <div className={styles.empty}>
            <div className={styles.emptyIcon} aria-hidden>◉</div>
            <h2 className={styles.emptyTitle}>Your feed is being prepared…</h2>
            <p className={styles.emptyMsg}>
              We're scanning Tallinn's event landscape. Your personalized Daily Five
              will be ready by 06:00 tomorrow morning.
            </p>
            <p className={styles.emptyHint}>
              In the meantime, new events are being classified and ranked for you.
            </p>
          </div>
        ) : (
          <ol className={styles.list} aria-label="Today's Daily Five">
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
