import { useState } from 'react';
import { api } from '../api/client';
import { getLocale } from '../lib/auth';
import {
  CARD_ANIMATION_DELAY_STEP_MS,
  CATEGORY_GRADIENTS,
  EUR_SYMBOL,
  FALLBACK_GRADIENT,
  FREE_LABEL,
  type Signal,
  toLocaleCode,
} from '../constants';
import styles from './EventCard.module.css';

export interface EventData {
  id: number;
  slug: string;
  title: string;
  starts_at: string;
  ends_at: string | null;
  venue_name: string | null;
  venue_address: string | null;
  url: string | null;
  image_url: string | null;
  price_min: number | null;
  price_max: number | null;
  currency: string | null;
  categories: string[];
  vibes: string[];
  why_go: string[];
  quality_score: number | null;
}

interface Props {
  event: EventData;
  index: number;
  onFeedbackSent?: () => void;
}

function categoryGradient(categories: string[]): string {
  const key = categories[0]?.toLowerCase().replace(/\s+/g, '_') ?? '';
  return CATEGORY_GRADIENTS[key] ?? FALLBACK_GRADIENT;
}

function formatPrice(min: number | null, max: number | null, currency: string | null): string | null {
  if (min === null && max === null) return null;
  const sym = currency === 'EUR' ? EUR_SYMBOL : currency ?? '';
  if (min === 0) return FREE_LABEL;
  if (min !== null && max !== null && min !== max) return `${sym}${min}–${sym}${max}`;
  if (min !== null) return `${sym}${min}`;
  return null;
}

function formatTime(iso: string): string {
  const localeCode = toLocaleCode(getLocale());
  const date = new Date(iso);
  const weekday = date.toLocaleDateString(localeCode, { weekday: 'short' });
  const day = date.toLocaleDateString(localeCode, { day: 'numeric', month: 'short' });
  const time = date.toLocaleTimeString(localeCode, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${weekday}, ${day} · ${time}`;
}

interface FeedbackButtonProps {
  signal: Signal;
  icon: string;
  label: string;
  activeSignal: Signal | null;
  pending: boolean;
  onPress: (signal: Signal) => void;
}

const ACTIVE_CLASS: Record<Signal, string> = {
  like:     styles.activeLike,
  dislike:  styles.activeDislike,
  bookmark: styles.activeBookmark,
};

function FeedbackButton({ signal, icon, label, activeSignal, pending, onPress }: FeedbackButtonProps) {
  const activeClass = ACTIVE_CLASS[signal];
  return (
    <button
      className={[styles.action, activeSignal === signal ? activeClass : ''].join(' ')}
      onClick={() => onPress(signal)}
      disabled={pending}
      aria-label={label}
      aria-pressed={activeSignal === signal}
      title={label}
    >
      {icon}
    </button>
  );
}

export default function EventCard({ event, index, onFeedbackSent }: Props) {
  const [activeSignal, setActiveSignal] = useState<Signal | null>(null);
  const [pending, setPending] = useState(false);

  async function sendFeedback(signal: Signal) {
    if (pending || activeSignal === signal) return;
    setPending(true);
    try {
      await api.post('/feedback', { event_id: event.id, signal });
      setActiveSignal(signal);
      onFeedbackSent?.();
    } catch {
      // Silently fail — feedback is best-effort
    } finally {
      setPending(false);
    }
  }

  const price = formatPrice(event.price_min, event.price_max, event.currency);

  return (
    <article
      className={styles.card}
      style={{ animationDelay: `${index * CARD_ANIMATION_DELAY_STEP_MS}ms` }}
    >
      <div className={styles.imageWrap}>
        {event.image_url ? (
          <img
            src={event.image_url}
            alt={event.title}
            className={styles.image}
            loading="lazy"
          />
        ) : (
          <div
            className={styles.placeholder}
            style={{ background: categoryGradient(event.categories) }}
            aria-hidden
          >
            <span className={styles.placeholderNum}>{String(index + 1).padStart(2, '0')}</span>
          </div>
        )}
        {price && <span className={styles.price}>{price}</span>}
      </div>

      <div className={styles.body}>
        <div className={styles.meta}>
          <time className={styles.time}>{formatTime(event.starts_at)}</time>
          {event.venue_name && (
            <span className={styles.venue}>{event.venue_name}</span>
          )}
        </div>

        <h2 className={styles.title}>
          {event.url ? (
            <a href={event.url} target="_blank" rel="noopener noreferrer" className={styles.titleLink}>
              {event.title}
            </a>
          ) : event.title}
        </h2>

        {event.why_go.length > 0 && (
          <ul className={styles.bullets} aria-label="Why go">
            {event.why_go.map((bullet, i) => (
              <li key={i} className={styles.bullet}>{bullet}</li>
            ))}
          </ul>
        )}
      </div>

      <div className={styles.actions}>
        <FeedbackButton signal="like"     icon="👍" label="Like"     activeSignal={activeSignal} pending={pending} onPress={sendFeedback} />
        <FeedbackButton signal="dislike"  icon="👎" label="Dislike"  activeSignal={activeSignal} pending={pending} onPress={sendFeedback} />
        <FeedbackButton signal="bookmark" icon="🔖" label="Bookmark" activeSignal={activeSignal} pending={pending} onPress={sendFeedback} />
        {event.url && (
          <a
            href={event.url}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.ticketsLink}
            onClick={() => api.post('/feedback', { event_id: event.id, signal: 'click_external' }).catch(() => undefined)}
          >
            Tickets →
          </a>
        )}
      </div>
    </article>
  );
}
