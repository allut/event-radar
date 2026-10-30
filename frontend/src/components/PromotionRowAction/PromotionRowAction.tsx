import { Link } from 'react-router-dom';
import { PROMOTION_EVENT_PARAM, PROMOTION_FORM_EVENT_PARAM } from '../../constants/organizerPromotions';
import { ROUTES } from '../../constants/routes';
import { useLocalePath } from '../../hooks/useLocalePath';
import { t, ti } from '../../i18n';
import type { PromotionRowFlags } from '../../lib/organizerPromotions';
import { withQueryParam } from '../../utils';
import PromotionBadge from '../PromotionBadge';
import styles from './PromotionRowAction.module.css';

interface PromotionRowActionProps {
  eventId: number;
  eventTitle: string;
  /** The row's `promotion` key; absent while the offer is off, so nothing renders. */
  promotion: PromotionRowFlags | undefined;
  locale: string;
}

/** The quiet "Promote" action on a promotable event row, or the Promotion's
 * status badge in its place while a request or Promotion is open. Shared by
 * Your events and a claim's events list. */
export default function PromotionRowAction({ eventId, eventTitle, promotion, locale }: PromotionRowActionProps) {
  const localePath = useLocalePath();
  if (!promotion) return null;

  if (promotion.badge) {
    const statusLabel = t(`promo_status_${promotion.badge}`, locale);
    return (
      <PromotionBadge
        status={promotion.badge}
        locale={locale}
        to={withQueryParam(localePath(ROUTES.organizerPromotions), PROMOTION_EVENT_PARAM, String(eventId))}
        ariaLabel={ti('promo_badge_aria', locale, { status: statusLabel, title: eventTitle })}
      />
    );
  }
  if (!promotion.promotable) return null;
  return (
    <Link
      to={withQueryParam(localePath(ROUTES.organizerPromotionRequest), PROMOTION_FORM_EVENT_PARAM, String(eventId))}
      className={styles.promote}
      aria-label={ti('promo_promote_aria', locale, { title: eventTitle })}
    >
      {t('promo_promote', locale)}
    </Link>
  );
}
