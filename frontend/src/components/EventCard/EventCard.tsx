import { Link } from 'react-router-dom';
import { CARD_ANIMATION_DELAY_STEP_MS, type Signal } from '../../constants';
import { t } from '../../i18n';
import { categoryGradient, cx, formatEventTime, formatPrice, padIndex, safeUrl, trackExternalClick } from '../../utils';
import { useFeedback } from '../../hooks/useFeedback';
import FeedbackButtonRow from '../FeedbackButtonRow';
import styles from './EventCard.module.css';

export interface EventData {
  id: number;
  slug: string;
  title: string;
  description: string | null;
  important_info: string | null;
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
  has_free_tier: boolean;
  categories: string[];
  vibes: string[];
  why_go: string[];
  quality_score: number | null;
  my_signal: Signal | null;
}

interface EventCardProps {
  event: EventData;
  index: number;
  locale: string;
  onFeedbackSent?: () => void;
  variant?: 'standard' | 'featured';
}

export default function EventCard({ event, index, locale, onFeedbackSent, variant = 'standard' }: EventCardProps) {
  const { activeSignal, pending, sendFeedback } = useFeedback(event.id, {
    initialSignal: event.my_signal,
    onChange: onFeedbackSent,
  });
  const isFeatured = variant === 'featured';

  const price = formatPrice(event.price_min, event.price_max, event.currency, locale, event.has_free_tier);
  const imageSrc = safeUrl(event.image_url);
  const ticketUrl = safeUrl(event.url);

  return (
    <article
      className={cx(styles.card, isFeatured && styles.featured)}
      style={{ animationDelay: `${index * CARD_ANIMATION_DELAY_STEP_MS}ms` }}
    >
      <div className={cx(styles.imageWrap, isFeatured && styles.featuredImageWrap)}>
        {imageSrc ? (
          <>
            <img src={imageSrc} alt="" aria-hidden className={styles.backdrop} loading="lazy" />
            <img src={imageSrc} alt={event.title} className={styles.image} loading="lazy" />
          </>
        ) : (
          <div
            className={styles.placeholder}
            style={{ background: categoryGradient(event.categories) }}
            aria-hidden
          >
            {!isFeatured && (
              <span className={styles.placeholderNum}>{padIndex(index + 1)}</span>
            )}
          </div>
        )}
        {isFeatured && (
          <span className={styles.numeral} aria-hidden>{padIndex(index + 1)}</span>
        )}
        {price && <span className={styles.price}>{price}</span>}
      </div>

      <div className={cx(styles.body, isFeatured && styles.featuredBody)}>
        <div className={cx(styles.meta, isFeatured && styles.featuredMeta)}>
          <time className={styles.time}>{formatEventTime(event.starts_at, locale)}</time>
          {event.venue_name && (
            <span className={styles.venue}>{event.venue_name}</span>
          )}
        </div>

        <h2 className={cx(styles.title, isFeatured && styles.featuredTitle)}>
          <Link to={`/events/${event.id}`} className={styles.titleLink}>
            {event.title}
          </Link>
        </h2>

        {event.why_go.length > 0 && (
          <ul className={cx(styles.bullets, isFeatured && styles.featuredBullets)} aria-label={t('why_go', locale)}>
            {event.why_go.map(bullet => (
              <li key={bullet} className={cx(styles.bullet, isFeatured && styles.featuredBullet)}>{bullet}</li>
            ))}
          </ul>
        )}
      </div>

      <div className={styles.actions}>
        <FeedbackButtonRow
          activeSignal={activeSignal}
          pending={pending}
          onPress={sendFeedback}
          locale={locale}
          variant={isFeatured ? 'detail' : 'card'}
        />
        {ticketUrl && (
          <a
            href={ticketUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.ticketsLink}
            onClick={() => trackExternalClick(event.id)}
          >
            {t('tickets', locale)}
          </a>
        )}
      </div>
    </article>
  );
}
