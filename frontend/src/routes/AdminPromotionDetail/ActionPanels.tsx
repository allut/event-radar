import { useId, useState, type FormEvent, type ReactNode } from 'react';
import DatePicker from '../../components/DatePicker';
import { ADMIN_LOCALE } from '../../constants/admin';
import { API } from '../../constants/api';
import {
  PROMOTION_DETAIL_COPY as COPY,
  PROMOTION_EDIT_SCOPE,
  PROMOTION_INVOICE_PREFIX,
  PROMOTION_REASON_ROWS,
  PROMOTION_REGISTRY_CODE_RE,
} from '../../constants/promotions';
import { formatEuro, isIsoDay, parseEuroToCents, type PromotionDetail } from '../../lib/promotions';
import { PROMOTION_STRIPE_COPY as STRIPE } from '../../constants/promotions';
import { tallinnToday, toDateStr } from '../../utils';
import styles from './AdminPromotionDetail.module.css';

/** One command the page runs: the request, resolved to the refreshed detail. */
export type PromotionCommand = () => Promise<unknown>;

export interface PanelProps {
  detail: PromotionDetail;
  /** The server refusal for the last attempt, shown inside the open panel. */
  serverError: string | null;
  pending: boolean;
  run: (command: PromotionCommand) => void;
  onCancel: () => void;
  post: (path: string, body: unknown) => PromotionCommand;
  patch: (path: string, body: unknown) => PromotionCommand;
}

interface ShellProps {
  heading: string;
  note?: string;
  error: string | null;
  confirmLabel: string;
  danger?: boolean;
  pending: boolean;
  onCancel: () => void;
  onSubmit: () => void;
  children: ReactNode;
}

function PanelShell({ heading, note, error, confirmLabel, danger, pending, onCancel, onSubmit, children }: ShellProps) {
  function submit(e: FormEvent) {
    e.preventDefault();
    onSubmit();
  }
  return (
    <form className={styles.panel} onSubmit={submit} noValidate>
      <h3 className={styles.panelTitle}>{heading}</h3>
      <div className={styles.panelFields}>{children}</div>
      {note && <p className={styles.note}>{note}</p>}
      <p className={styles.error} role="alert">
        {error}
      </p>
      <div className={styles.panelButtons}>
        <button type="submit" className={danger ? styles.dangerButton : styles.primaryButton} disabled={pending}>
          {confirmLabel}
        </button>
        <button type="button" className={styles.plainButton} onClick={onCancel}>
          {COPY.cancel}
        </button>
      </div>
    </form>
  );
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={htmlFor}>
        {label}
      </label>
      {children}
    </div>
  );
}

export function MarkPaidPanel({ detail, serverError, pending, run, onCancel, post }: PanelProps) {
  const id = useId();
  const [invoice, setInvoice] = useState(detail.invoice_reference ?? '');
  const [error, setError] = useState<string | null>(null);
  function submit() {
    const trimmed = invoice.trim();
    if (trimmed && !trimmed.startsWith(PROMOTION_INVOICE_PREFIX)) return setError(COPY.invoiceInvalid);
    setError(null);
    run(post(API.adminPromotionMarkPaid(detail.id), { invoice_reference: trimmed || null }));
  }
  return (
    <PanelShell
      heading="Mark paid"
      error={error ?? serverError}
      confirmLabel="Confirm mark paid"
      pending={pending}
      onCancel={onCancel}
      onSubmit={submit}
    >
      <Field label={COPY.invoiceOptional} htmlFor={`${id}-inv`}>
        <input
          id={`${id}-inv`}
          className={`${styles.input} ${styles.mono}`}
          placeholder={`${PROMOTION_INVOICE_PREFIX}0001`}
          value={invoice}
          onChange={(e) => setInvoice(e.target.value)}
        />
      </Field>
    </PanelShell>
  );
}

export function EditPanel({ detail, serverError, pending, run, onCancel, patch }: PanelProps) {
  const id = useId();
  const full = detail.actions.edit_scope === PROMOTION_EDIT_SCOPE.full;
  const [start, setStart] = useState(detail.start_date);
  const [end, setEnd] = useState(detail.end_date);
  const [name, setName] = useState(detail.advertiser_legal_name);
  const [registry, setRegistry] = useState(detail.advertiser_registry_code);
  const [email, setEmail] = useState(detail.billing_email ?? '');
  const [invoice, setInvoice] = useState(detail.invoice_reference ?? '');
  const [error, setError] = useState<string | null>(null);

  // A live window can only be shortened, never to a day before today; a
  // not-yet-started one ends no earlier than its (edited) start.
  const endMin = full ? (isIsoDay(start) ? start : undefined) : toDateStr(tallinnToday());

  function submit() {
    const body: Record<string, string | null> = {};
    if (full && start !== detail.start_date) body.start_date = start;
    if (end !== detail.end_date) body.end_date = end;
    if (full) {
      if (name.trim() !== detail.advertiser_legal_name) body.advertiser_legal_name = name.trim();
      if (registry.trim() !== detail.advertiser_registry_code) body.advertiser_registry_code = registry.trim();
      if (email.trim() !== (detail.billing_email ?? '')) body.billing_email = email.trim() || null;
      if (invoice.trim() !== (detail.invoice_reference ?? '')) body.invoice_reference = invoice.trim() || null;
    }
    if (Object.keys(body).length === 0) return setError(COPY.noChanges);
    if ((body.start_date !== undefined && !isIsoDay(start)) || (body.end_date !== undefined && !isIsoDay(end))) {
      return setError('Pick valid dates.');
    }
    if (body.advertiser_legal_name === '') return setError('Advertiser legal name is required.');
    if (body.advertiser_registry_code !== undefined && !PROMOTION_REGISTRY_CODE_RE.test(registry.trim())) {
      return setError('Registry code must be 8 digits.');
    }
    if (typeof body.invoice_reference === 'string' && !body.invoice_reference.startsWith(PROMOTION_INVOICE_PREFIX)) {
      return setError(COPY.invoiceInvalid);
    }
    setError(null);
    run(patch(API.adminPromotionDetail(detail.id), body));
  }

  return (
    <PanelShell
      heading={full ? COPY.editFullHeading : COPY.editShortenHeading}
      note={full ? COPY.editFullNote : COPY.editShortenNote}
      error={error ?? serverError}
      confirmLabel="Save changes"
      pending={pending}
      onCancel={onCancel}
      onSubmit={submit}
    >
      <Field label="Start date" htmlFor={`${id}-start`}>
        <DatePicker
          id={`${id}-start`}
          ariaLabel="Start date"
          locale={ADMIN_LOCALE}
          dateOnly
          required
          value={start}
          max={detail.event.last_day}
          disabled={!full}
          onChange={setStart}
        />
      </Field>
      <Field label="End date" htmlFor={`${id}-end`}>
        <DatePicker
          id={`${id}-end`}
          ariaLabel="End date"
          locale={ADMIN_LOCALE}
          dateOnly
          required
          value={end}
          min={endMin}
          max={full ? detail.event.last_day : detail.end_date}
          onChange={setEnd}
        />
      </Field>
      {full && (
        <>
          <Field label="Advertiser legal name" htmlFor={`${id}-name`}>
            <input id={`${id}-name`} className={styles.input} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Registry code" htmlFor={`${id}-reg`}>
            <input
              id={`${id}-reg`}
              className={`${styles.input} ${styles.mono}`}
              inputMode="numeric"
              value={registry}
              onChange={(e) => setRegistry(e.target.value)}
            />
          </Field>
          <Field label="Billing email" htmlFor={`${id}-email`}>
            <input
              id={`${id}-email`}
              className={styles.input}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Invoice reference" htmlFor={`${id}-inv`}>
            <input
              id={`${id}-inv`}
              className={`${styles.input} ${styles.mono}`}
              value={invoice}
              onChange={(e) => setInvoice(e.target.value)}
            />
          </Field>
        </>
      )}
    </PanelShell>
  );
}

export function RepointPanel({ detail, serverError, pending, run, onCancel, post }: PanelProps) {
  const id = useId();
  const candidates = detail.repoint_candidates;
  const [target, setTarget] = useState('');
  const [error, setError] = useState<string | null>(null);
  function submit() {
    if (!target) return setError(COPY.repointPick);
    setError(null);
    run(post(API.adminPromotionRepoint(detail.id), { event_id: Number(target) }));
  }
  return (
    <PanelShell
      heading={COPY.repointHeading}
      note={candidates.length === 0 ? COPY.repointNone : undefined}
      error={error ?? serverError}
      confirmLabel="Confirm re-point"
      pending={pending || candidates.length === 0}
      onCancel={onCancel}
      onSubmit={submit}
    >
      <Field label={COPY.repointLabel} htmlFor={`${id}-target`}>
        <select id={`${id}-target`} className={styles.input} value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Choose an event…</option>
          {candidates.map((c) => (
            <option key={c.event_id} value={c.event_id}>
              {c.title}
            </option>
          ))}
        </select>
      </Field>
    </PanelShell>
  );
}

function ReasonPanel({
  serverError,
  pending,
  run,
  onCancel,
  post,
  heading,
  note,
  path,
  confirmLabel,
}: PanelProps & { heading: string; note?: string; path: string; confirmLabel: string }) {
  const id = useId();
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  function submit() {
    if (!reason.trim()) return setError(COPY.reasonRequired);
    setError(null);
    run(post(path, { reason: reason.trim() }));
  }
  return (
    <PanelShell
      heading={heading}
      note={note}
      error={error ?? serverError}
      confirmLabel={confirmLabel}
      danger
      pending={pending}
      onCancel={onCancel}
      onSubmit={submit}
    >
      <Field label={COPY.reasonLabel} htmlFor={`${id}-reason`}>
        <textarea
          id={`${id}-reason`}
          className={styles.input}
          rows={PROMOTION_REASON_ROWS}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </Field>
    </PanelShell>
  );
}

export function EndPanel(props: PanelProps) {
  return (
    <ReasonPanel
      {...props}
      heading={COPY.endHeading}
      note={COPY.endNote}
      path={API.adminPromotionEnd(props.detail.id)}
      confirmLabel="Confirm end early"
    />
  );
}

export function VoidPanel(props: PanelProps) {
  return (
    <ReasonPanel
      {...props}
      heading={COPY.voidHeading}
      note={props.detail.awaiting_checkout ? STRIPE.voidNote : undefined}
      path={API.adminPromotionVoid(props.detail.id)}
      confirmLabel="Confirm void"
    />
  );
}

/** Withdraw this Promotion (#620): ends it with feature_withdrawn and records
 * a full refund of the unused days. The server refuses with 409 while the
 * slots flag is on; that message shows here. */
export function WithdrawPanel({ detail, serverError, pending, run, onCancel, post }: PanelProps) {
  return (
    <PanelShell
      heading={COPY.withdrawHeading}
      note={COPY.withdrawNote}
      error={serverError}
      confirmLabel={COPY.withdrawConfirm}
      danger
      pending={pending}
      onCancel={onCancel}
      onSubmit={() => run(post(API.adminPromotionWithdraw(detail.id), {}))}
    >
      {null}
    </PanelShell>
  );
}

/** Record or issue a refund. The suggestion is the server's `refund_prefill`:
 * (unused + paused days) x the price paid per day. A Stripe-paid Promotion is
 * issued (credit note and card refund); any other is only recorded. */
export function RefundPanel({ detail, serverError, pending, run, onCancel, post }: PanelProps) {
  const id = useId();
  const prefill = detail.refund_prefill ?? null;
  const stripe = prefill?.mode === 'stripe';
  const max = prefill?.remaining_cents ?? detail.actions.refundable_cents;
  const suggested = prefill ? prefill.suggested_cents : max;
  const [amount, setAmount] = useState((suggested / 100).toFixed(2));
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  function submit() {
    const cents = parseEuroToCents(amount);
    if (cents === null || cents > max) return setError(`Enter an amount up to ${formatEuro(max)}.`);
    if (!note.trim()) return setError(COPY.refundNoteRequired);
    setError(null);
    run(post(API.adminPromotionRefund(detail.id), { amount_cents: cents, note: note.trim() }));
  }
  const typed = parseEuroToCents(amount);
  return (
    <PanelShell
      heading={stripe ? STRIPE.refundHeading : COPY.refundHeading}
      note={
        stripe
          ? STRIPE.refundCardNote(detail.invoice_reference)
          : `Up to ${formatEuro(max)} (price paid, incl. VAT). Off-platform payments only; nothing is sent to the Organizer.`
      }
      error={error ?? serverError}
      confirmLabel={stripe ? STRIPE.issueRefund(typed === null ? null : formatEuro(typed)) : 'Confirm refund'}
      pending={pending}
      onCancel={onCancel}
      onSubmit={submit}
    >
      {prefill && (
        <div className={styles.calc}>
          <div className={styles.calcTitle}>{STRIPE.refundSuggested}{formatEuro(prefill.suggested_cents)}</div>
          <div className={styles.mono}>
            ({prefill.unused_days} unused + {prefill.paused_days} paused) days × {formatEuro(prefill.gross_per_day_cents)} per day ={' '}
            {formatEuro((prefill.unused_days + prefill.paused_days) * prefill.gross_per_day_cents)}
          </div>
          <div className={styles.calcHint}>
            {stripe ? STRIPE.refundPerDayNote(formatEuro(detail.gross_price_cents), detail.days) : STRIPE.refundManualNote}
          </div>
        </div>
      )}
      <div className={`${styles.field} ${styles.refundAmount}`}>
        <label className={styles.label} htmlFor={`${id}-amount`}>
          {COPY.refundAmountLabel}
        </label>
        <input
          id={`${id}-amount`}
          className={`${styles.input} ${styles.mono}`}
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        {stripe && <span className={styles.fieldHint}>{STRIPE.refundMax(formatEuro(max))}</span>}
      </div>
      <div className={`${styles.field} ${styles.refundNote}`}>
        <label className={styles.label} htmlFor={`${id}-note`}>
          {COPY.refundNoteLabel}
        </label>
        <input
          id={`${id}-note`}
          className={styles.input}
          placeholder={stripe ? STRIPE.refundPlaceholder : undefined}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>
    </PanelShell>
  );
}
