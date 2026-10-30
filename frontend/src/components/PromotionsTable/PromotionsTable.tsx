import { Link } from 'react-router-dom';
import { ROUTES } from '../../constants/routes';
import { PROMOTION_STRIPE_COPY } from '../../constants/promotions';
import { PROMOTION_INVOICE_SOURCE_MANUAL } from '../../_generated/sharedConstants';
import { formatWindow, isStripePaid, promotionPill, promotionPriceLabel, type PromotionRow } from '../../lib/promotions';
import styles from './PromotionsTable.module.css';

const TONE_CLASS = {
  live: styles.pillLive,
  scheduled: styles.pillScheduled,
  finished: styles.pillFinished,
  attention: styles.pillAttention,
} as const;

/** Promotion rows with computed state pills and the not-showing reason
 * under the pill. Admin register: hairlines, mono data, no corners. */
export default function PromotionsTable({ rows, ariaBusy }: { rows: PromotionRow[]; ariaBusy?: boolean }) {
  return (
    <div className={styles.scroll} aria-busy={ariaBusy}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Event</th>
            <th>Advertiser</th>
            <th>Window</th>
            <th>Price</th>
            <th>Status</th>
            <th>{PROMOTION_STRIPE_COPY.invoiceColumn}</th>
            <th><span className={styles.srOnly}>Details</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => {
            const pill = promotionPill(p);
            return (
              <tr key={p.id}>
                <td>
                  <Link to={ROUTES.adminEventDetail(p.event_id)} className={styles.eventLink}>
                    {p.event_title}
                  </Link>
                </td>
                <td>{p.advertiser_legal_name}</td>
                <td className={styles.mono}>{formatWindow(p.start_date, p.end_date)}</td>
                <td>
                  <span className={styles.mono}>{promotionPriceLabel(p)}</span>
                  {isStripePaid(p) ? (
                    <div className={styles.chipRow}><span className={`${styles.chip} ${styles.chipStripe}`}>{PROMOTION_STRIPE_COPY.chip}</span></div>
                  ) : p.invoice_source === PROMOTION_INVOICE_SOURCE_MANUAL && !p.is_complimentary ? (
                    <div className={styles.chipRow}><span className={styles.chip}>{PROMOTION_STRIPE_COPY.bankChip}</span></div>
                  ) : null}
                </td>
                <td>
                  <span className={`${styles.pill} ${TONE_CLASS[pill.tone]}`}>{pill.label}</span>
                  {pill.reason && <div className={styles.reason}>{pill.reason}</div>}
                </td>
                <td>
                  {p.invoice_url && p.invoice_reference ? (
                    <a href={p.invoice_url} className={`${styles.docLink} ${styles.mono}`} target="_blank" rel="noopener noreferrer">
                      {p.invoice_reference} ↗
                    </a>
                  ) : p.invoice_reference ? (
                    <span className={styles.mono}>{p.invoice_reference}</span>
                  ) : (
                    <span className={styles.muted}>—</span>
                  )}
                </td>
                <td>
                  <Link to={ROUTES.adminPromotionDetail(p.id)} className={styles.eventLink}>
                    Manage
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
