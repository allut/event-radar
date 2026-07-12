import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { clearToken } from '../../lib/auth';
import { t, ti } from '../../i18n';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import EventCard, { type EventData } from '../../components/EventCard';
import EmptyState from '../../components/EmptyState';
import PageState from '../../components/PageState';
import TopBar from '../../components/TopBar';
import { formatHourMinute, formatTodayDate, padIndex } from '../../utils';
import styles from './Feed.module.css';

interface FeedResponse {
  feed_date: string;
  events: EventData[];
  built_at: string | null;
}

export default function Feed() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { locale, handleLocaleChange } = useLocaleMutation(['feed']);

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
      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <header className={styles.masthead}>
          <div className={styles.mastheadTop}>
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
          <p className={styles.tagline}>{t('tagline', locale)}</p>
          <hr className={styles.rule} />
        </header>

        {events.length === 0 ? (
          <EmptyState
            icon="◉"
            title={t('feed_empty_title', locale)}
            message={t('feed_empty_msg', locale)}
            hint={t('feed_empty_hint', locale)}
          />
        ) : (
          <ol className={styles.list} aria-label={t('daily_five', locale)}>
            <li key={events[0].id} className={styles.featuredItem}>
              <EventCard event={events[0]} index={0} locale={locale} onFeedbackSent={handleFeedbackSent} variant="featured" />
            </li>
            {events.slice(1).map((event, i) => (
              <li key={event.id} className={styles.standardItem}>
                <span className={styles.indexNumeral} aria-hidden>{padIndex(i + 2)}</span>
                <EventCard event={event} index={i + 1} locale={locale} onFeedbackSent={handleFeedbackSent} />
              </li>
            ))}
          </ol>
        )}
      </main>
    </div>
  );
}
