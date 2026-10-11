import { memo } from 'react';
import { Link } from 'react-router-dom';
import { UI_STATE } from '../../constants/core';
import type { Signal } from '../../constants/feedback';
import { ROUTES } from '../../constants/routes';
import { t } from '../../i18n';
import { cardAnimationDelayMs, categoryGradient, cx, formatEventTime, formatPrice, padIndex, safeUrl, shareEvent, trackExternalClick } from '../../utils';
import { useEventReport } from '../../hooks/useEventReport';
import { useFeedback } from '../../hooks/useFeedback';
import type { EventCardNav } from '../../hooks/useEventCardNav';
import { useToast } from '../../hooks/useToast';
import EventOverflowMenu from '../EventOverflowMenu';
import FeedbackButtonRow from '../FeedbackButtonRow';
import ReportModal from '../ReportModal';
import Toast from '../Toast';
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
  reported: boolean;
}

interface EventCardProps {
  event: EventData;
  index: number;
  locale: string;
  // Router/auth context resolved once by the parent list (useEventCardNav) so
  // no card subscribes to the router or auth store itself (issue #455).
  nav: EventCardNav;
  onFeedbackSent?: () => void;
  variant?: 'standard' | 'featured';
  // Presentational mode for anonymous surfaces (e.g. the public landing showcase):
  // hides the feedback row and skips click tracking, since both POST to auth-only
  // /feedback and would bounce a logged-out visitor to /login.
  readOnly?: boolean;
  // Grid layouts (Explore, Saved) need the title to reserve 2 lines of height
  // so sibling cards' bullets stay aligned across a row. Single-column lists
  // (Feed) have no sibling to align against, so they can opt out and avoid
  // the dead space a 1-line title leaves above the bullets.
  alignTitle?: boolean;
  // Anonymous /explore (issue #235): when set, a save/thumbs press is
  // intercepted client-side before any API call — useFeedback's sendFeedback
  // is never invoked — and this is called with the pressed signal instead,
  // so the caller can open the sign-in modal and fire its own analytics.
  onFeedbackBlocked?: (signal: Signal) => void;
  // Fired with this card's list `index` when the title link is clicked, so
  // the caller (Explore) can track explore_card_click with the position.
  // Navigation itself is unaffected — this is additive, not an
  // interception. Takes `index` as an argument (rather than the caller
  // closing over it per card) so Explore can pass one referentially-stable
  // callback for every card instead of a fresh closure per card per render,
  // which would defeat this component's memo below.
  onCardClick?: (index: number) => void;
}

function EventCard({ event, index, locale, nav, onFeedbackSent, variant = 'standard', readOnly = false, alignTitle = true, onFeedbackBlocked, onCardClick }: EventCardProps) {
  const { activeSignal, pending, sendFeedback } = useFeedback(event.id, {
    initialSignal: event.my_signal,
    onChange: onFeedbackSent,
  });

  function handleFeedbackPress(signal: Signal) {
    if (onFeedbackBlocked) {
      onFeedbackBlocked(signal);
      return;
    }
    sendFeedback(signal);
  }
  const { localePath, authed, onLoginRequired } = nav;
  const { toast, showToast } = useToast();
  const { reportOpen, reported, openReportModal, closeReportModal, handleReportSubmitted } = useEventReport(event.reported, event.id, authed, onLoginRequired);
  const isFeatured = variant === 'featured';

  const price = formatPrice(event.price_min, event.price_max, event.currency, locale, event.has_free_tier);
  const imageSrc = safeUrl(event.image_url);
  const ticketUrl = safeUrl(event.url);

  async function handleShare() {
    const url = `${window.location.origin}${localePath(ROUTES.eventDetail(event.id))}`;
    const result = await shareEvent(event.title, url);
    if (result === 'shared' || result === 'cancelled') return;
    showToast(result === 'copied' ? UI_STATE.success : UI_STATE.error, t(result === 'copied' ? 'link_copied' : 'share_failed', locale));
  }

  const actionsRow = (!readOnly || ticketUrl) && (
    <div className={styles.actions}>
      {!readOnly && (
        <FeedbackButtonRow
          activeSignal={activeSignal}
          pending={pending}
          onPress={handleFeedbackPress}
          locale={locale}
          variant={isFeatured ? 'detail' : 'card'}
        />
      )}
      {ticketUrl && (
        <a
          href={ticketUrl}
          target="_blank"
          rel="noopener noreferrer"
          className={styles.ticketsLink}
          onClick={readOnly ? undefined : () => trackExternalClick(event.id)}
        >
          {t('tickets', locale)}
        </a>
      )}
    </div>
  );

  return (
    <article
      className={cx(styles.card, isFeatured && styles.featured)}
      style={{ animationDelay: `${cardAnimationDelayMs(index)}ms` }}
    >
      <div className={styles.clickable}>
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

        {!readOnly && (
          <div className={styles.overflowWrap}>
            <EventOverflowMenu
              locale={locale}
              reported={reported}
              onShare={handleShare}
              onReport={openReportModal}
              triggerClassName={styles.cardOverflowTrigger}
            />
          </div>
        )}

        <div className={cx(styles.body, isFeatured && styles.featuredBody)}>
          <div className={cx(styles.meta, isFeatured && styles.featuredMeta)}>
            <time className={styles.time}>{formatEventTime(event.starts_at, locale)}</time>
            {event.venue_name && (
              <span className={styles.venue}>{event.venue_name}</span>
            )}
          </div>

          <h2 className={cx(styles.title, isFeatured && styles.featuredTitle)}>
            <Link
              to={localePath(ROUTES.eventDetail(event.id))}
              className={cx(styles.titleLink, styles.stretched)}
              onClick={onCardClick ? () => onCardClick(index) : undefined}
            >
              <span className={cx(styles.titleClamp, isFeatured && styles.featuredTitleClamp, !isFeatured && !alignTitle && styles.titleClampFlush)}>
                {event.title}
              </span>
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
      </div>

      {actionsRow}

      {!readOnly && toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
      {!readOnly && reportOpen && (
        <ReportModal
          open={reportOpen}
          onClose={closeReportModal}
          eventId={event.id}
          locale={locale}
          onSubmitted={handleReportSubmitted}
        />
      )}
    </article>
  );
}

// event.my_signal drives useFeedback's initial state internally, so the card
// only needs to re-render when the event object reference or the display
// props change — not on every parent re-render (e.g. Explore's search input
// keystrokes), since the event list is stable while typing.
export default memo(EventCard);
