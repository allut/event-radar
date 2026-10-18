import { useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { adminApi } from '../../api/client';
import { API, QUERY_KEYS } from '../../constants/api';
import { UI_STATE } from '../../constants/core';
import {
  PROMOTION_ACTION,
  PROMOTION_ACTION_LABELS,
  PROMOTION_DETAIL_COPY as COPY,
  PROMOTION_GATE_SHOWN,
  PROMOTION_SNAPSHOT_TRIGGER_LABELS,
  type PromotionActionKey,
} from '../../constants/promotions';
import { ROUTES } from '../../constants/routes';
import { ADMIN_GENERIC_ERROR } from '../../constants/admin';
import {
  DAILY_STAT_COLUMNS,
  dailyStatTotals,
  detailReason,
  formatDateTime,
  formatEuro,
  formatWindow,
  gateLabel,
  promotionPill,
  formatDay,
  type PromotionDailyStatsResponse,
  type PromotionDetail,
} from '../../lib/promotions';
import { apiErrorMessage } from '../../utils';
import PageState from '../../components/PageState';
import {
  EditPanel,
  EndPanel,
  MarkPaidPanel,
  RefundPanel,
  RepointPanel,
  VoidPanel,
  type PanelProps,
  type PromotionCommand,
} from './ActionPanels';
import styles from './AdminPromotionDetail.module.css';

const TONE_CLASS = {
  live: styles.pillLive,
  scheduled: styles.pillScheduled,
  finished: styles.pillFinished,
  attention: styles.pillAttention,
} as const;

// Action bar order; each button follows the API's `actions` flag of the same name.
const ACTION_ORDER: PromotionActionKey[] = [
  PROMOTION_ACTION.markPaid,
  PROMOTION_ACTION.edit,
  PROMOTION_ACTION.repoint,
  PROMOTION_ACTION.end,
  PROMOTION_ACTION.void,
  PROMOTION_ACTION.refund,
];
const DANGER_ACTIONS: ReadonlySet<PromotionActionKey> = new Set([PROMOTION_ACTION.end, PROMOTION_ACTION.void]);

const PANELS: Record<PromotionActionKey, (props: PanelProps) => ReactNode> = {
  [PROMOTION_ACTION.markPaid]: (p) => <MarkPaidPanel {...p} />,
  [PROMOTION_ACTION.edit]: (p) => <EditPanel {...p} />,
  [PROMOTION_ACTION.repoint]: (p) => <RepointPanel {...p} />,
  [PROMOTION_ACTION.end]: (p) => <EndPanel {...p} />,
  [PROMOTION_ACTION.void]: (p) => <VoidPanel {...p} />,
  [PROMOTION_ACTION.refund]: (p) => <RefundPanel {...p} />,
};

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className={styles.section}>
      <h2 id={id} className={styles.sectionTitle}>
        {title}
      </h2>
      {children}
    </section>
  );
}

function recordRows(p: PromotionDetail): [string, ReactNode][] {
  const mono = (v: string | null) => <span className={styles.mono}>{v ?? '—'}</span>;
  return [
    ['Advertiser', p.advertiser_legal_name],
    ['Registry code', mono(p.advertiser_registry_code)],
    ['Billing email', p.billing_email ?? '—'],
    ['Organizer', p.organizer_name ?? '—'],
    ['Granted by', p.granted_by ?? '—'],
    ['Net price', p.is_complimentary ? '€0.00 (complimentary)' : formatEuro(p.net_price_cents)],
    [`VAT ${Number(p.vat_rate_percent)}%`, formatEuro(p.vat_cents)],
    ['Gross', formatEuro(p.gross_price_cents)],
    ['Invoice', mono(p.invoice_reference)],
    ['Paid at', p.paid_at ? formatDateTime(p.paid_at) : '—'],
    ['Refunded', formatEuro(p.refunded_cents)],
    ...(p.complimentary_note ? ([['Complimentary note', p.complimentary_note]] as [string, ReactNode][]) : []),
    ...(p.refund_note ? ([['Refund note', p.refund_note]] as [string, ReactNode][]) : []),
  ];
}

/** Admin Promotion detail (#601, #606): state, the lifecycle commands the
 * server allows, the commercial record, per-day delivery, content snapshots
 * and the audit trail. Commands open inline panels, never modals. */
export default function AdminPromotionDetail({ promotionId }: { promotionId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState<PromotionActionKey | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);

  const detailKey = [QUERY_KEYS.adminPromotionDetail, promotionId];
  const detailQuery = useQuery({
    queryKey: detailKey,
    queryFn: () => adminApi.get<PromotionDetail>(API.adminPromotionDetail(promotionId)),
  });
  const statsQuery = useQuery({
    queryKey: [QUERY_KEYS.adminPromotionDailyStats, promotionId],
    queryFn: () => adminApi.get<PromotionDailyStatsResponse>(API.adminPromotionDailyStats(promotionId)),
  });

  const command = useMutation({
    mutationFn: (run: PromotionCommand) => run(),
    onSuccess: (payload) => {
      queryClient.setQueryData(detailKey, payload);
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotions] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionCapStrip] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionContext] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionDailyStats, promotionId] });
      setOpen(null);
      setServerError(null);
    },
    onError: (err) => {
      setServerError(apiErrorMessage(err, ADMIN_GENERIC_ERROR));
      // Another admin may have moved the Promotion on: refresh what the buttons allow.
      void queryClient.invalidateQueries({ queryKey: detailKey });
    },
  });

  if (detailQuery.isLoading) return <PageState kind={UI_STATE.loading} message="Loading…" inline />;
  if (detailQuery.isError || !detailQuery.data) {
    return <PageState kind={UI_STATE.error} message={COPY.loadFailed} inline />;
  }
  const p = detailQuery.data;
  const pill = promotionPill(p);
  const days = statsQuery.data?.days ?? [];
  const reason = detailReason(p, days);
  const totals = dailyStatTotals(days);
  const anyAction = ACTION_ORDER.some((k) => p.actions[k]);
  const hint = anyAction
    ? COPY.actionsHint
    : p.actions.refund
      ? COPY.noActions
      : COPY.noActionsAtAll;

  function toggle(key: PromotionActionKey) {
    setServerError(null);
    setOpen((current) => (current === key ? null : key));
  }

  const panelProps = {
    detail: p,
    serverError,
    pending: command.isPending,
    run: (run: PromotionCommand) => command.mutate(run),
    onCancel: () => toggle(open as PromotionActionKey),
    post: (path: string, body: unknown): PromotionCommand => () => adminApi.post(path, body),
    patch: (path: string, body: unknown): PromotionCommand => () => adminApi.patch(path, body),
  };

  return (
    <div className={styles.page}>
      <Link to={ROUTES.adminPromotions} className={styles.back}>
        {COPY.back}
      </Link>

      <div className={styles.head}>
        <h1 className={styles.title}>{p.event_title}</h1>
        <span className={`${styles.pill} ${TONE_CLASS[pill.tone]}`}>{pill.label}</span>
        <span className={styles.window}>{formatWindow(p.start_date, p.end_date)}</span>
        {reason && <div className={styles.reason}>{reason}</div>}
        <div className={styles.sub}>
          <Link to={ROUTES.adminEventDetail(p.event_id)} className={styles.link}>
            Event #{p.event_id}
          </Link>
          {' · '}
          {p.organizer_name ?? '—'} · {p.days} days · starts {formatDay(p.start_date)}
        </div>
      </div>

      <Section id="actions-heading" title={COPY.actionsHeading}>
        <div className={styles.actions}>
          {ACTION_ORDER.map((key) => (
            <button
              key={key}
              type="button"
              className={DANGER_ACTIONS.has(key) ? styles.dangerButton : key === PROMOTION_ACTION.markPaid ? styles.primaryButton : styles.plainButton}
              disabled={!p.actions[key]}
              aria-expanded={open === key}
              onClick={() => toggle(key)}
            >
              {PROMOTION_ACTION_LABELS[key]}
            </button>
          ))}
        </div>
        <p className={styles.note}>{hint}</p>
        {open !== null && p.actions[open] && <div key={open}>{PANELS[open](panelProps)}</div>}
      </Section>

      <Section id="record-heading" title={COPY.recordHeading}>
        <dl className={styles.record}>
          {recordRows(p).map(([label, value]) => (
            <div key={label} className={styles.recordRow}>
              <dt className={styles.recordTerm}>{label}</dt>
              <dd className={styles.recordValue}>{value}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section id="delivery-heading" title={COPY.deliveryHeading}>
        {statsQuery.isError ? (
          <PageState kind={UI_STATE.error} message={COPY.loadFailed} inline />
        ) : (
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th className={styles.left}>Day</th>
                  <th className={styles.left}>Gate</th>
                  {DAILY_STAT_COLUMNS.map((c) => (
                    <th key={c.key}>{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {days.length === 0 ? (
                  <tr>
                    <td colSpan={DAILY_STAT_COLUMNS.length + 2} className={`${styles.left} ${styles.muted}`}>
                      {COPY.noDays}
                    </td>
                  </tr>
                ) : (
                  <>
                    {days.map((d) => (
                      <tr key={d.day} className={d.gate_outcome !== null && d.gate_outcome !== PROMOTION_GATE_SHOWN ? styles.paused : undefined}>
                        <td className={`${styles.left} ${styles.mono} ${styles.nowrap}`}>{formatDay(d.day)}</td>
                        <td className={styles.left}>{gateLabel(d)}</td>
                        {DAILY_STAT_COLUMNS.map((c) => (
                          <td key={c.key} className={styles.mono}>
                            {d[c.key]}
                          </td>
                        ))}
                      </tr>
                    ))}
                    <tr className={styles.total}>
                      <td className={styles.left}>Total</td>
                      <td />
                      {totals.map((n, i) => (
                        <td key={DAILY_STAT_COLUMNS[i].key} className={styles.mono}>
                          {n}
                        </td>
                      ))}
                    </tr>
                  </>
                )}
              </tbody>
            </table>
          </div>
        )}
        <p className={styles.note}>{COPY.deliveryNote}</p>
      </Section>

      <Section id="snapshots-heading" title={COPY.snapshotsHeading}>
        {p.snapshots.length === 0 ? (
          <p className={styles.muted}>{COPY.noSnapshots}</p>
        ) : (
          <div className={styles.snapshots}>
            {p.snapshots.map((s) => (
              <div key={s.id} className={styles.snapshot}>
                <strong>{s.label_text}</strong>
                <span>{[s.title.et, s.title.en, s.title.ru].filter(Boolean).join(' / ')}</span>
                <span>
                  {[s.venue_name, s.event_starts_at ? formatDateTime(s.event_starts_at) : null].filter(Boolean).join(' · ')}
                </span>
                {s.description_excerpt && <span className={styles.muted}>{s.description_excerpt}</span>}
                <span className={styles.muted}>
                  {formatDateTime(s.taken_at)} · {PROMOTION_SNAPSHOT_TRIGGER_LABELS[s.trigger] ?? s.trigger} ·{' '}
                  {formatWindow(s.start_date, s.end_date)} · {formatEuro(s.net_price_cents)} net
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section id="audit-heading" title={COPY.auditHeading}>
        {p.audit.length === 0 ? (
          <p className={styles.muted}>{COPY.noAudit}</p>
        ) : (
          <ul className={styles.audit}>
            {p.audit.map((a) => (
              <li key={`${a.created_at}-${a.action}`} className={styles.auditRow}>
                <span className={`${styles.mono} ${styles.muted}`}>{formatDateTime(a.created_at)}</span>
                <span>{a.action}</span>
                <span className={styles.muted}>{a.result}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
