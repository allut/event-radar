import { PROMOTION_COPY } from '../../constants/promotions';
import { formatDay, formatDayNumber, formatWeekday, type CapDay } from '../../lib/promotions';
import styles from './PromotionCapStrip.module.css';

interface PromotionCapStripProps {
  days: CapDay[];
  /** The window being picked in the grant form, highlighted on the strip. */
  selected?: { start: string; end: string } | null;
  todayIso: string;
}

/** The 14-day cap strip: one bar per Tallinn day, `cap` slots tall, filled
 * from the bottom with live then reserved Promotions. */
export default function PromotionCapStrip({ days, selected, todayIso }: PromotionCapStripProps) {
  return (
    <div>
      <div className={styles.strip}>
        {days.map((d) => {
          const full = d.reserved >= d.cap;
          const picked = selected != null && d.date >= selected.start && d.date <= selected.end;
          const classes = [styles.day, picked ? styles.pick : '', d.date === todayIso ? styles.today : '']
            .filter(Boolean)
            .join(' ');
          const reservedOnly = d.reserved - d.live;
          return (
            <div key={d.date} className={classes} data-full={full} data-picked={picked}>
              <div
                className={full ? styles.barFull : styles.bar}
                role="img"
                aria-label={`${formatDay(d.date)}: ${d.live} live, ${reservedOnly} reserved, ${d.reserved} of ${d.cap}`}
              >
                {Array.from({ length: d.cap }, (_, k) => (
                  <i key={k} className={k < d.live ? styles.slotLive : k < d.reserved ? styles.slotReserved : styles.slot} />
                ))}
              </div>
              <div className={styles.count}>{`${d.reserved}/${d.cap}`}</div>
              <div className={styles.label}>
                {formatWeekday(d.date)} {formatDayNumber(d.date)}
              </div>
            </div>
          );
        })}
      </div>
      <div className={styles.legend}>
        <span><b className={styles.swatchLive} />{PROMOTION_COPY.legendLive}</span>
        <span><b className={styles.swatchReserved} />{PROMOTION_COPY.legendReserved}</span>
        <span><b className={styles.swatchFull} />{PROMOTION_COPY.legendFull}</span>
        {selected && <span><b className={styles.swatchPick} />{PROMOTION_COPY.legendSelected}</span>}
      </div>
    </div>
  );
}
