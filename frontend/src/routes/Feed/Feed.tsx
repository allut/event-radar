import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { t, ti } from '../../i18n';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useLogout } from '../../hooks/useLogout';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import EventCard, { type EventData } from '../../components/EventCard';
import EmptyState from '../../components/EmptyState';
import PageState from '../../components/PageState';
import TopBar from '../../components/TopBar';
import SeoTags from '../../components/SeoTags';
import { formatHourMinute, formatIsoDate, formatTodayDate, padIndex, titleWithBrand, withLocaleQuery } from '../../utils';
import { API, QUERY_KEYS, ROUTES, UI_STATE } from '../../constants';
import styles from './Feed.module.css';

interface FeedResponse {
  feed_date: string;
  events: EventData[];
  built_at: string | null;
  is_stale: boolean;
}

export default function Feed() {
  const { locale, handleLocaleChange, isPending: localePending } = useLocaleMutation({ publicRoute: true });
  const localePath = useLocalePath();
  const handleLogout = useLogout();
  const seoMeta = useSeoMeta({ title: titleWithBrand(t('seo_title_feed', locale), locale), locale, path: ROUTES.home });

  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.feed, locale],
    queryFn: () => api.get<FeedResponse>(withLocaleQuery(API.feed, locale)),
    retry: false,
  });

  if (isLoading) {
    return (
      <>
        <SeoTags meta={seoMeta} />
        <PageState kind={UI_STATE.loading} message={t('loading', locale)} />
      </>
    );
  }

  if (isError) {
    return (
      <>
        <SeoTags meta={seoMeta} />
        <PageState kind={UI_STATE.error} message={t('feed_error', locale)} />
      </>
    );
  }

  const events = data?.events ?? [];

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} localeDisabled={localePending} />

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

        {data?.is_stale && events.length > 0 && (
          <p className={styles.staleNotice}>
            {ti('feed_stale_notice', locale, { date: formatIsoDate(data.feed_date, locale) })}
          </p>
        )}

        <Link to={localePath(ROUTES.explore)} className={styles.promo}>
          <div className={styles.promoText}>
            <h2 className={styles.promoTitle}>{t('feed_promo_title', locale)}</h2>
            <p className={styles.promoMsg}>{t('feed_promo_msg', locale)}</p>
          </div>
          <span className={styles.promoCta}>{t('feed_promo_cta', locale)}</span>
        </Link>

        {events.length === 0 ? (
          <EmptyState
            eyebrow={t('daily_five', locale)}
            title={t('feed_empty_title', locale)}
            message={t('feed_empty_msg', locale)}
            hint={t('feed_empty_hint', locale)}
          />
        ) : (
          <ol className={styles.list} aria-label={t('daily_five', locale)}>
            <li key={events[0].id} className={styles.featuredItem}>
              <EventCard event={events[0]} index={0} locale={locale} variant="featured" />
            </li>
            {events.slice(1).map((event, i) => (
              <li key={event.id} className={styles.standardItem}>
                <span className={styles.indexNumeral} aria-hidden>{padIndex(i + 2)}</span>
                <EventCard event={event} index={i + 1} locale={locale} />
              </li>
            ))}
          </ol>
        )}
      </main>
    </div>
  );
}
