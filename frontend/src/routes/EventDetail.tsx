import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { getLocale } from '../lib/auth';
import { toLocaleCode, type Signal, SIGNAL_CONFIG } from '../constants';
import { t, ti } from '../i18n';
import { categoryGradient, formatEventDateTime, formatPrice, makeActiveClassMap } from '../utils';
import { type EventData } from '../components/EventCard';
import { useFeedback } from '../hooks/useFeedback';
import styles from './EventDetail.module.css';

interface EventDetailData extends EventData {
  language: string | null;
}

const ACTIVE_CLASS = makeActiveClassMap(styles);

export default function EventDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const locale = getLocale();

  const { data, isLoading, isError } = useQuery({
    queryKey: ['event', id],
    queryFn: () => api.get<EventDetailData>(`/events/${id}`),
    enabled: Boolean(id),
    retry: false,
  });

  const { activeSignal, pending, sendFeedback } = useFeedback(data?.id ?? 0);

  async function handleTicketsClick() {
    if (!data) return;
    api.post('/feedback', { event_id: data.id, signal: 'click_external' }).catch(() => undefined);
  }

  if (isLoading) {
    return (
      <div className={styles.centered}>
        <span className={styles.spinner} aria-label={t('loading_event', locale)} />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className={styles.centered}>
        <p className={styles.errorMsg}>{t('event_not_found', locale)}</p>
        <button className={styles.backBtn} onClick={() => navigate('/')}>{t('back_to_feed_link', locale)}</button>
      </div>
    );
  }

  const price = formatPrice(data.price_min, data.price_max, data.currency);
  const mapsUrl = data.lat && data.lng
    ? `https://www.google.com/maps/search/?api=1&query=${data.lat},${data.lng}`
    : data.venue_address
    ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(data.venue_address)}`
    : null;

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => navigate(-1)} aria-label={t('back', locale)}>
          {t('back', locale)}
        </button>
        <div className={styles.logoWrap}>
          <span className={styles.radar} aria-hidden>◉</span>
          <span className={styles.brand}>{t('brand', locale)}</span>
        </div>
      </header>

      <main className={styles.main}>
        <div className={styles.hero}>
          {data.image_url ? (
            <img src={data.image_url} alt={data.title} className={styles.heroImage} />
          ) : (
            <div
              className={styles.heroPlaceholder}
              style={{ background: categoryGradient(data.categories) }}
              aria-hidden
            />
          )}
          {price && <span className={styles.price}>{price}</span>}
        </div>

        <div className={styles.content}>
          <div className={styles.meta}>
            <time className={styles.time}>{formatEventDateTime(data.starts_at, locale)}</time>
            {data.ends_at && (
              <span className={styles.ends}>
                {ti('ends_at', locale, {
                  time: new Date(data.ends_at).toLocaleTimeString(toLocaleCode(locale), { hour: '2-digit', minute: '2-digit', hour12: false }),
                })}
              </span>
            )}
          </div>

          <h1 className={styles.title}>{data.title}</h1>

          {(data.venue_name || data.venue_address) && (
            <div className={styles.venue}>
              {data.venue_name && <span className={styles.venueName}>{data.venue_name}</span>}
              {data.venue_address && (
                <span className={styles.venueAddress}>{data.venue_address}</span>
              )}
              {mapsUrl && (
                <a href={mapsUrl} target="_blank" rel="noopener noreferrer" className={styles.mapLink}>
                  {t('view_on_map', locale)}
                </a>
              )}
            </div>
          )}

          {data.why_go.length > 0 && (
            <ul className={styles.bullets} aria-label={t('why_go', locale)}>
              {data.why_go.map((bullet, i) => (
                <li key={i} className={styles.bullet}>{bullet}</li>
              ))}
            </ul>
          )}

          {data.description && (
            <p className={styles.description}>{data.description}</p>
          )}

          {(data.categories.length > 0 || data.vibes.length > 0) && (
            <div className={styles.tags}>
              {data.categories.map(cat => (
                <span key={cat} className={styles.tag}>{cat.replace(/_/g, ' ')}</span>
              ))}
              {data.vibes.map(vibe => (
                <span key={vibe} className={`${styles.tag} ${styles.tagVibe}`}>{vibe.replace(/_/g, ' ')}</span>
              ))}
            </div>
          )}

          <div className={styles.actions}>
            <div className={styles.feedbackGroup}>
              {(Object.entries(SIGNAL_CONFIG) as [Signal, { icon: string; label: string }][]).map(([signal, { icon }]) => (
                <button
                  key={signal}
                  className={[styles.action, activeSignal === signal ? ACTIVE_CLASS[signal] : ''].join(' ')}
                  onClick={() => sendFeedback(signal)}
                  disabled={pending}
                  aria-label={t(`signal_${signal}`, locale)}
                  aria-pressed={activeSignal === signal}
                >
                  {icon}
                </button>
              ))}
            </div>
            {data.url && (
              <a
                href={data.url}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.ticketsBtn}
                onClick={handleTicketsClick}
              >
                {t('get_tickets', locale)}
              </a>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
