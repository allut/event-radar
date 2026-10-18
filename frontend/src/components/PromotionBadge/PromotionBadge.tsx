import { Link } from 'react-router-dom';
import { PROMOTION_STATUS_TONE } from '../../constants/organizerPromotions';
import { t } from '../../i18n';
import { cx } from '../../utils';
import styles from './PromotionBadge.module.css';

interface PromotionBadgeProps {
  /** A GET /organizer/promotions status word (`requested`, `live`, ...). */
  status: string;
  locale: string;
  /** Renders the badge as a link (the event rows' badge opens Promotions). */
  to?: string;
  ariaLabel?: string;
  className?: string;
}

/** The square status badge for a request or Promotion, in the Organizer
 * portal's badge register: uppercase hairline box, one tone per status. */
export default function PromotionBadge({ status, locale, to, ariaLabel, className }: PromotionBadgeProps) {
  const classes = cx(styles.badge, styles[`tone_${PROMOTION_STATUS_TONE[status] ?? 'muted'}`], to && styles.link, className);
  const label = t(`promo_status_${status}`, locale);
  if (to) {
    return (
      <Link to={to} className={classes} aria-label={ariaLabel}>
        {label}
      </Link>
    );
  }
  return <span className={classes}>{label}</span>;
}
