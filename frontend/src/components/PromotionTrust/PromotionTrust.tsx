import { useQuery } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import { API, QUERY_KEYS } from '../../constants/api';
import { UI_STATE } from '../../constants/core';
import {
  PROMOTION_CONSENT_SOURCE_LABELS,
  PROMOTION_PERIODS,
  PROMOTION_PERIOD_LABELS,
  PROMOTION_SURFACE_LABELS,
  PROMOTION_TRUST_COPY as COPY,
  type PromotionPeriod,
} from '../../constants/promotions';
import {
  evaluateTripwires,
  formatDay,
  formatWindow,
  type TrustPeriod,
  type TrustResponse,
} from '../../lib/promotions';
import PageState from '../PageState';
import ComplaintLogger from './ComplaintLogger';
import PromotionWithdraw from './PromotionWithdraw';
import styles from './PromotionTrust.module.css';

function MetricRow({ label, sub, value, section }: { label: string; sub?: string; value: number | string; section?: boolean }) {
  return (
    <div className={section ? styles.metricSection : styles.metric}>
      <span className={styles.metricKey}>
        {label}
        {sub && <span className={styles.metricSub}>{sub}</span>}
      </span>
      <span className={styles.metricValue}>{value}</span>
    </div>
  );
}

function SubRow({ label, value }: { label: string; value: number | string }) {
  return (
    <div className={styles.metric}>
      <span className={styles.subKey}>{label}</span>
      <span className={styles.subValue}>{value}</span>
    </div>
  );
}

function PeriodColumn({ period, data, range, primary }: { period: PromotionPeriod; data: TrustPeriod; range: string; primary: boolean }) {
  return (
    <div className={primary ? styles.periodPrimary : styles.period}>
      <div className={styles.periodHead}>
        <b>{PROMOTION_PERIOD_LABELS[period]}</b>
        <span className={styles.rangeHint}>{range}</span>
      </div>
      <MetricRow label={COPY.reports} sub={COPY.reportsSub(data.promotions_taken_down, data.reports_resolved)} value={data.reports_on_promoted} />
      <MetricRow label={COPY.consentsGranted} sub={COPY.consentsGrantedSub} value={data.consents_granted} />
      <MetricRow label={COPY.withdrawals} value={data.consent_withdrawals.total} section />
      {Object.entries(data.consent_withdrawals.by_source).map(([source, n]) => (
        <SubRow key={source} label={PROMOTION_CONSENT_SOURCE_LABELS[source] ?? source} value={n} />
      ))}
      <MetricRow label={COPY.slotsServed} value={data.slots_served.toLocaleString('en')} section />
      {Object.entries(data.slots_served_by_surface).map(([surface, n]) => (
        <SubRow key={surface} label={PROMOTION_SURFACE_LABELS[surface] ?? surface} value={n.toLocaleString('en')} />
      ))}
      <MetricRow label={COPY.webOpens} value={data.web_opens} />
      <MetricRow label={COPY.dislikes} sub={COPY.adminOnly} value={data.slot_dislikes} />
      <MetricRow label={COPY.complaints} value={data.complaints} />
    </div>
  );
}

/** Trust review (#620) on /admin/promotions: the denominators and both
 * periods, the stop-selling tripwires worked out from the rolling 4 weeks,
 * the complaint logger and Withdraw. Read only except the logger and the
 * Withdraw commands; nothing here flips a flag. */
export default function PromotionTrust() {
  const trust = useQuery({
    queryKey: [QUERY_KEYS.adminPromotionTrust],
    queryFn: () => adminApi.get<TrustResponse>(API.adminPromotionTrust),
  });

  if (trust.isLoading) return <PageState kind={UI_STATE.loading} message="Loading…" inline />;
  if (trust.isError || !trust.data) return <PageState kind={UI_STATE.error} message={COPY.loadFailed} inline />;

  const data = trust.data;
  const today = data.as_of.slice(0, 10);
  const wires = evaluateTripwires(data.periods.rolling_4_weeks);
  const tripped = wires.filter((w) => w.tripped).length;
  const ranges: Record<PromotionPeriod, string> = {
    rolling_4_weeks: formatWindow(data.window_start, today),
    since_launch: COPY.sinceFirstSale,
  };

  return (
    <div className={styles.stack}>
      <section aria-labelledby="trust-heading">
        <h2 id="trust-heading" className={styles.sectionTitle}>{COPY.heading}</h2>
        <div className={styles.current}>
          <div className={styles.tile}>
            <span className={styles.tileNumber}>{data.current.live_promotions}</span>
            <span className={styles.tileLabel}>{COPY.livePromotions}</span>
          </div>
          <div className={styles.tile}>
            <span className={styles.tileNumber}>{data.current.consenters}</span>
            <span className={styles.tileLabel}>{COPY.currentConsenters}</span>
          </div>
          <div className={styles.tile}>
            <span className={styles.tileNumber}>{data.periods.since_launch.complaints}</span>
            <span className={styles.tileLabel}>{COPY.complaintsLogged}</span>
          </div>
        </div>
        <div className={styles.periods}>
          {PROMOTION_PERIODS.map((period, i) => (
            <PeriodColumn key={period} period={period} data={data.periods[period]} range={ranges[period]} primary={i === 0} />
          ))}
        </div>
        <p className={styles.hint}>{COPY.panelHint(formatDay(data.window_start))}</p>
      </section>

      <section aria-labelledby="tripwires-heading">
        <h2 id="tripwires-heading" className={styles.sectionTitle}>{COPY.tripwiresHeading}</h2>
        <ul className={styles.tripwires}>
          {wires.map((w) => (
            <li key={w.key} className={styles.tripwire}>
              <span className={`${styles.pill} ${w.tripped ? styles.pillDanger : styles.pillLive}`}>{w.tripped ? COPY.tripped : COPY.clear}</span>
              <div>
                <div className={w.tripped ? styles.ruleHit : styles.rule}>{w.rule}</div>
                <div className={styles.figures}>{w.figures}</div>
              </div>
            </li>
          ))}
        </ul>
        <div className={tripped > 0 ? `${styles.alert} ${styles.alertDanger} ${styles.verdict}` : `${styles.alert} ${styles.verdict}`}>
          <div className={styles.alertTitle}>{tripped > 0 ? COPY.verdictTripped(tripped) : COPY.verdictClear}</div>
          <div>{tripped > 0 ? COPY.verdictTrippedBody : COPY.verdictClearBody}</div>
        </div>
        <p className={styles.hint}>{COPY.thresholdsHint}</p>
      </section>

      <ComplaintLogger complaints={data.recent_complaints} />
      <PromotionWithdraw />
    </div>
  );
}
