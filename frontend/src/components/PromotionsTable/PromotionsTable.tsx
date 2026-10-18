import { Link } from 'react-router-dom';
import { ROUTES } from '../../constants/routes';
import { formatWindow, promotionPill, promotionPriceLabel, type PromotionRow } from '../../lib/promotions';
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
                <td className={styles.mono}>{promotionPriceLabel(p)}</td>
                <td>
                  <span className={`${styles.pill} ${TONE_CLASS[pill.tone]}`}>{pill.label}</span>
                  {pill.reason && <div className={styles.reason}>{pill.reason}</div>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
