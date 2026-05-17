import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { getLocale } from '../lib/auth';
import { CARD_ANIMATION_DELAY_STEP_MS, SIGNAL_CONFIG, type Signal } from '../constants';
import { t } from '../i18n';
import { categoryGradient, formatEventTime, formatPrice, makeActiveClassMap } from '../utils';
import { useFeedback } from '../hooks/useFeedback';
import styles from './EventCard.module.css';

export interface EventData {
  id: number;
  slug: string;
  title: string;
  description: string | null;
  starts_at: string;
  ends_at: string | null;
  venue_name: string | null;
  venue_address: string | null;
  lat: number | null;
  lng: number | null;
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

interface FeedbackButtonProps {
  signal: Signal;
  icon: string;
  label: string;
  activeSignal: Signal | null;
  pending: boolean;
  onPress: (signal: Signal) => void;
}

const ACTIVE_CLASS = makeActiveClassMap(styles);

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
  const locale = getLocale();
  const { activeSignal, pending, sendFeedback } = useFeedback(event.id, onFeedbackSent);

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
          <time className={styles.time}>{formatEventTime(event.starts_at, locale)}</time>
          {event.venue_name && (
            <span className={styles.venue}>{event.venue_name}</span>
          )}
        </div>

        <h2 className={styles.title}>
          <Link to={`/events/${event.id}`} className={styles.titleLink}>
            {event.title}
          </Link>
        </h2>

        {event.why_go.length > 0 && (
          <ul className={styles.bullets} aria-label={t('why_go', locale)}>
            {event.why_go.map((bullet, i) => (
              <li key={i} className={styles.bullet}>{bullet}</li>
            ))}
          </ul>
        )}
      </div>

      <div className={styles.actions}>
        {(Object.entries(SIGNAL_CONFIG) as [Signal, { icon: string; label: string }][]).map(([signal, { icon }]) => (
          <FeedbackButton
            key={signal}
            signal={signal}
            icon={icon}
            label={t(`signal_${signal}`, locale)}
            activeSignal={activeSignal}
            pending={pending}
            onPress={sendFeedback}
          />
        ))}
        {event.url && (
          <a
            href={event.url}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.ticketsLink}
            onClick={() => api.post('/feedback', { event_id: event.id, signal: 'click_external' }).catch(() => undefined)}
          >
            {t('tickets', locale)}
          </a>
        )}
      </div>
    </article>
  );
}
