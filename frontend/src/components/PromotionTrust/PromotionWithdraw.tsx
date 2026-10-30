import { useState } from 'react';
import { useMutation, useQueries, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import { ADMIN_GENERIC_ERROR } from '../../constants/admin';
import { API, PAGE_PARAM, QUERY_KEYS } from '../../constants/api';
import {
  ADMIN_PROMOTIONS_WITHDRAW_LIMIT,
  PROMOTION_STATE,
  PROMOTION_STATUS,
  PROMOTION_TRUST_COPY as COPY,
} from '../../constants/promotions';
import {
  formatEuro,
  formatWindow,
  isStripePaid,
  unusedDays,
  withdrawErrorMessage,
  withdrawRefundCents,
  type PromotionRow,
} from '../../lib/promotions';
import styles from './PromotionTrust.module.css';

interface ListResponse {
  today: string;
  promotions: PromotionRow[];
}

interface WithdrawnItem {
  row: PromotionRow;
  unused: number;
  refund: number;
}

interface WithdrawAllResponse {
  withdrawn: { id: number; unused_days: number; refund_cents: number }[];
  skipped: { id: number; code: string }[];
}

interface Outcome {
  done: WithdrawnItem[];
  skipped: { row: PromotionRow | undefined; id: number; code: string }[];
}

const WITHDRAWABLE_STATES = [PROMOTION_STATE.live, PROMOTION_STATE.scheduled];

/** Merges the per-state lists. Module scope keeps the function stable, so
 * `useQueries` re-runs it only when a list changes, not on every render. */
function combineLists(lists: UseQueryResult<ListResponse>[]) {
  return {
    today: lists.find((l) => l.data)?.data?.today ?? '',
    rows: lists
      .flatMap((l) => l.data?.promotions ?? [])
      .filter((p) => p.status === PROMOTION_STATUS.paid)
      .sort((a, b) => a.id - b.id),
    loadFailed: lists.some((l) => l.isError),
  };
}

/** Withdraw (#620): end every paid Promotion with feature_withdrawn once the
 * slots flag is off. The server owns the rule (409 slots_still_enabled), so
 * the buttons stay clickable and show its refusal. */
export default function PromotionWithdraw() {
  const queryClient = useQueryClient();
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [ack, setAck] = useState(false);
  const [allError, setAllError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const { today, rows, loadFailed } = useQueries({
    queries: WITHDRAWABLE_STATES.map((state) => ({
      queryKey: [QUERY_KEYS.adminPromotionWithdrawable, state],
      queryFn: () =>
        adminApi.get<ListResponse>(
          `${API.adminPromotions}?state=${state}&${PAGE_PARAM.limit}=${ADMIN_PROMOTIONS_WITHDRAW_LIMIT}&${PAGE_PARAM.offset}=0`,
        ),
    })),
    combine: combineLists,
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionWithdrawable] });
    void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotions] });
    void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionCapStrip] });
    void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionTrust] });
    void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionDetail] });
  }

  const withdrawOne = useMutation({
    mutationFn: (row: PromotionRow) =>
      adminApi.post<{ refunded_cents: number }>(API.adminPromotionWithdraw(row.id), {}),
    onSuccess: (detail, row) => {
      setRowErrors((e) => ({ ...e, [row.id]: '' }));
      setOutcome({
        done: [{ row, unused: unusedDays(row, today), refund: detail.refunded_cents - row.refunded_cents }],
        skipped: [],
      });
      refresh();
    },
    onError: (err, row) => setRowErrors((e) => ({ ...e, [row.id]: withdrawErrorMessage(err, COPY.withdrawFailed) })),
  });

  const withdrawAll = useMutation({
    mutationFn: () => adminApi.post<WithdrawAllResponse>(API.adminPromotionWithdrawAll, {}),
    onSuccess: (result) => {
      const byId = new Map(rows.map((r) => [r.id, r]));
      setOutcome({
        done: result.withdrawn.flatMap((w) => {
          const row = byId.get(w.id);
          return row ? [{ row, unused: w.unused_days, refund: w.refund_cents }] : [];
        }),
        skipped: result.skipped.map((s) => ({ row: byId.get(s.id), id: s.id, code: s.code })),
      });
      setConfirming(false);
      setAllError(null);
      refresh();
    },
    onError: (err) => setAllError(withdrawErrorMessage(err, ADMIN_GENERIC_ERROR)),
  });

  function confirmAll() {
    if (!ack) return setAllError(COPY.withdrawAckRequired);
    setAllError(null);
    withdrawAll.mutate();
  }

  const refundTotal = outcome?.done.reduce((n, d) => n + d.refund, 0) ?? 0;
  const stripeTitles = outcome?.done.filter((d) => isStripePaid(d.row) && d.refund > 0).map((d) => d.row.event_title) ?? [];

  return (
    <section aria-labelledby="withdraw-heading">
      <h2 id="withdraw-heading" className={styles.sectionTitle}>{COPY.withdrawHeading}</h2>
      <div className={styles.alert}>
        <div className={styles.alertTitle}>{COPY.slotsOnTitle}</div>
        <div>{COPY.slotsOnBody}</div>
      </div>
      <ol className={`${styles.steps} ${styles.stepsGap}`}>
        {COPY.steps.map((step) => <li key={step}>{step}</li>)}
      </ol>

      <div className={`${styles.tableScroll} ${styles.tableGap}`}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>{COPY.colEvent}</th>
              <th>{COPY.colWindow}</th>
              <th className={styles.num}>{COPY.colUnused}</th>
              <th className={styles.num}>{COPY.colRefund}</th>
              <th><span className={styles.srOnly}>Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {loadFailed ? (
              <tr><td colSpan={5} className={styles.error}>{COPY.loadWithdrawFailed}</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={5} className={styles.muted}>{COPY.noneLeft}</td></tr>
            ) : (
              rows.map((row) => {
                const unused = unusedDays(row, today);
                return (
                  <tr key={row.id}>
                    <td>
                      {row.event_title}
                      {isStripePaid(row) && <> <span className={`${styles.chip} ${styles.chipStripe}`}>Stripe</span></>}
                      {row.is_complimentary && <> <span className={styles.chip}>Complimentary</span></>}
                    </td>
                    <td className={styles.mono}>{formatWindow(row.start_date, row.end_date)}</td>
                    <td className={styles.num}>{unused}</td>
                    <td className={styles.num}>
                      {row.is_complimentary ? COPY.noRefund : formatEuro(withdrawRefundCents(row, unused))}
                    </td>
                    <td>
                      <button
                        type="button"
                        className={`${styles.dangerButton} ${styles.smallButton}`}
                        aria-label={`${COPY.withdraw} ${row.event_title}`}
                        disabled={withdrawOne.isPending}
                        onClick={() => withdrawOne.mutate(row)}
                      >
                        {COPY.withdraw}
                      </button>
                      <div className={styles.rowError} role="alert">{rowErrors[row.id]}</div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className={`${styles.actions} ${styles.tableGap}`}>
        <button
          type="button"
          className={styles.dangerButton}
          disabled={rows.length === 0}
          onClick={() => {
            setAck(false);
            setAllError(null);
            setConfirming(true);
          }}
        >
          {COPY.withdrawAll(rows.length)}
        </button>
      </div>

      {confirming && (
        <div className={styles.panel}>
          <h3 className={styles.panelTitle}>{COPY.withdrawAllHeading(rows.length)}</h3>
          <p className={styles.panelBody}>{COPY.withdrawAllBody}</p>
          <label className={styles.check}>
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            <span>{COPY.withdrawAck}</span>
          </label>
          <p className={styles.error} role="alert">{allError}</p>
          <div className={styles.panelButtons}>
            <button type="button" className={styles.dangerButton} disabled={withdrawAll.isPending} onClick={confirmAll}>
              Withdraw all
            </button>
            <button type="button" className={styles.plainButton} onClick={() => setConfirming(false)}>Cancel</button>
          </div>
        </div>
      )}

      {outcome && outcome.done.length > 0 && (
        <div className={`${styles.alert} ${styles.alertSuccess} ${styles.outcome}`} role="status">
          <div className={styles.alertTitle}>{COPY.withdrawn(outcome.done.length, formatEuro(refundTotal))}</div>
          <ul className={`${styles.steps} ${styles.stepsPlain}`}>
            {outcome.done.map((d) => (
              <li key={d.row.id}>
                <span className={styles.mono}>#{d.row.id}</span> {d.row.event_title} · {COPY.withdrawnUnused(d.unused)} ·{' '}
                {d.refund > 0 ? COPY.withdrawnRefund(formatEuro(d.refund)) : COPY.withdrawnNothing}
              </li>
            ))}
          </ul>
          <div className={styles.hint}>
            {COPY.withdrawnHint}
            {stripeTitles.length > 0 && COPY.withdrawnStripe(stripeTitles.join(', '))}
          </div>
        </div>
      )}
      {outcome && outcome.skipped.length > 0 && (
        <div className={`${styles.alert} ${styles.alertDanger} ${styles.outcome}`} role="alert">
          <div className={styles.alertTitle}>{COPY.skipped(outcome.skipped.length)}</div>
          <ul className={`${styles.steps} ${styles.stepsPlain}`}>
            {outcome.skipped.map((s) => (
              <li key={s.id}>
                <span className={styles.mono}>#{s.id}</span> {s.row?.event_title ?? ''} · <span className={styles.mono}>{s.code}</span>
              </li>
            ))}
          </ul>
          <div className={styles.hint}>{COPY.skippedHint}</div>
        </div>
      )}
    </section>
  );
}
