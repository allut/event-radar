import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { getLocale } from '../lib/auth';
import { toLocaleCode, type Signal } from '../constants';
import { categoryGradient, formatPrice, makeActiveClassMap } from '../utils';
import { type EventData } from '../components/EventCard';
import styles from './EventDetail.module.css';

interface EventDetailData extends EventData {
  language: string | null;
}

function formatDateTime(iso: string, locale: string): string {
  const localeCode = toLocaleCode(locale);
  const date = new Date(iso);
  const weekday = date.toLocaleDateString(localeCode, { weekday: 'long' });
  const day = date.toLocaleDateString(localeCode, { day: 'numeric', month: 'long', year: 'numeric' });
  const time = date.toLocaleTimeString(localeCode, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${weekday}, ${day} · ${time}`;
}

const ACTIVE_CLASS = makeActiveClassMap(styles);

export default function EventDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const locale = getLocale();

  const [activeSignal, setActiveSignal] = useState<Signal | null>(null);
  const [pending, setPending] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['event', id],
    queryFn: () => api.get<EventDetailData>(`/events/${id}`),
    enabled: Boolean(id),
    retry: false,
  });

  async function sendFeedback(signal: Signal) {
    if (pending || activeSignal === signal || !data) return;
    setPending(true);
    try {
      await api.post('/feedback', { event_id: data.id, signal });
      setActiveSignal(signal);
    } catch {
      // best-effort
    } finally {
      setPending(false);
    }
  }

  async function handleTicketsClick() {
    if (!data) return;
    api.post('/feedback', { event_id: data.id, signal: 'click_external' }).catch(() => undefined);
  }

  if (isLoading) {
    return (
      <div className={styles.centered}>
        <span className={styles.spinner} aria-label="Loading event…" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className={styles.centered}>
        <p className={styles.errorMsg}>Event not found or unavailable.</p>
        <button className={styles.backBtn} onClick={() => navigate('/')}>← Back to feed</button>
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
        <button className={styles.backBtn} onClick={() => navigate(-1)} aria-label="Go back">
          ← Back
        </button>
        <div className={styles.logoWrap}>
          <span className={styles.radar} aria-hidden>◉</span>
          <span className={styles.brand}>Event Radar</span>
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
            <time className={styles.time}>{formatDateTime(data.starts_at, locale)}</time>
            {data.ends_at && (
              <span className={styles.ends}>
                ends {new Date(data.ends_at).toLocaleTimeString(toLocaleCode(locale), { hour: '2-digit', minute: '2-digit', hour12: false })}
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
                  View on map →
                </a>
              )}
            </div>
          )}

          {data.why_go.length > 0 && (
            <ul className={styles.bullets} aria-label="Why go">
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
              {(['like', 'dislike', 'bookmark'] as Signal[]).map(signal => (
                <button
                  key={signal}
                  className={[styles.action, activeSignal === signal ? ACTIVE_CLASS[signal] : ''].join(' ')}
                  onClick={() => sendFeedback(signal)}
                  disabled={pending}
                  aria-label={signal.charAt(0).toUpperCase() + signal.slice(1)}
                  aria-pressed={activeSignal === signal}
                >
                  {signal === 'like' ? '👍' : signal === 'dislike' ? '👎' : '🔖'}
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
                Get tickets →
              </a>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
