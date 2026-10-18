import { useId, useMemo, useState, type FormEvent } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import { API, QUERY_KEYS } from '../../constants/api';
import { UI_STATE } from '../../constants/core';
import {
  PROMOTION_COPY,
  PROMOTION_ERROR_START_CODES,
  PROMOTION_INVOICE_PREFIX,
  PROMOTION_NOTE_ROWS,
  PROMOTION_REGISTRY_CODE_RE,
  PROMOTION_REQUEST_COPY as REQUEST_COPY,
} from '../../constants/promotions';
import { ADMIN_GENERIC_ERROR, ADMIN_LOCALE } from '../../constants/admin';
import {
  formatDay,
  formatEuro,
  formatWindow,
  isIsoDay,
  priceLine,
  restrictionTag,
  type CapStripResponse,
  type PromotionContext,
  type PromotionRequestRow,
  type PromotionValidation,
} from '../../lib/promotions';
import { apiErrorMessage } from '../../utils';
import DatePicker from '../DatePicker';
import PageState from '../PageState';
import PromotionCapStrip from '../PromotionCapStrip';
import styles from './PromotionGrantForm.module.css';

interface PromotionGrantFormProps {
  eventId: string;
  onNotify: (status: typeof UI_STATE.success | typeof UI_STATE.error, message: string) => void;
  /** Grants this pending request instead (#615): the form starts from its
   * dates and advertiser fields, and saving also marks it granted. */
  request?: PromotionRequestRow;
  onDone?: () => void;
  /** Closes the form without granting; shown as Cancel in request mode. */
  onCancel?: () => void;
}

/** Grant Promotion (#600): admin direct grant for one event. Dates validate
 * live against the server's window, overlap and cap rules; the price line
 * and the cap strip's selection follow the dates. With `request` (#615) it
 * is the request queue's grant form, prefilled and editable. */
export default function PromotionGrantForm({ eventId, onNotify, request, onDone, onCancel }: PromotionGrantFormProps) {
  const queryClient = useQueryClient();
  const ids = useId();
  const [start, setStart] = useState(request?.start_date ?? '');
  const [end, setEnd] = useState(request?.end_date ?? '');
  const [name, setName] = useState<string | null>(request?.advertiser_legal_name ?? null);
  const [registry, setRegistry] = useState(request?.advertiser_registry_code ?? '');
  const [invoice, setInvoice] = useState('');
  const [email, setEmail] = useState<string | null>(request ? (request.billing_email ?? '') : null);
  const [complimentary, setComplimentary] = useState(false);
  const [note, setNote] = useState('');
  const [cleared, setCleared] = useState(false);
  const [clearNote, setClearNote] = useState('');

  const context = useQuery({
    queryKey: [QUERY_KEYS.adminPromotionContext, eventId],
    queryFn: () => adminApi.get<PromotionContext>(API.adminPromotionContext(eventId)),
  });
  const strip = useQuery({
    queryKey: [QUERY_KEYS.adminPromotionCapStrip],
    queryFn: () => adminApi.get<CapStripResponse>(API.adminPromotionCapStrip),
  });

  // Days already at the cap: greyed out and unselectable. The server's
  // /validate answer stays authoritative for overlap and window rules.
  const fullDays = useMemo(
    () => new Set((strip.data?.days ?? []).filter((d) => d.free <= 0).map((d) => d.date)),
    [strip.data],
  );

  const datesPicked = isIsoDay(start) && isIsoDay(end);
  const validation = useQuery({
    queryKey: [QUERY_KEYS.adminPromotionValidate, eventId, start, end, complimentary],
    queryFn: () =>
      adminApi.get<PromotionValidation>(
        `${API.adminPromotionValidate(eventId)}?start_date=${start}&end_date=${end}&is_complimentary=${complimentary}`,
      ),
    enabled: datesPicked,
    placeholderData: keepPreviousData,
  });

  const grant = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      adminApi.post(request ? API.adminPromotionRequestGrant(request.id) : API.adminPromotionGrant(eventId), body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotions] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionRequests] });
      if (request) {
        void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionCapStrip] });
        onNotify(UI_STATE.success, REQUEST_COPY.granted(request.event_title));
        onDone?.();
        return;
      }
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionCapStrip] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionContext, eventId] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionValidate, eventId] });
      setStart('');
      setEnd('');
      setNote('');
      setInvoice('');
      setComplimentary(false);
      onNotify(UI_STATE.success, PROMOTION_COPY.granted);
    },
    onError: (err) => {
      // Another admin may have resolved the request first: refresh the queue.
      if (request) void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionRequests] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionCapStrip] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionValidate, eventId] });
      onNotify(UI_STATE.error, apiErrorMessage(err, ADMIN_GENERIC_ERROR));
    },
  });

  if (context.isLoading) return <PageState kind={UI_STATE.loading} message="Loading…" inline />;
  if (context.isError || !context.data) {
    return <PageState kind={UI_STATE.error} message={PROMOTION_COPY.loadFailed} inline />;
  }
  const ctx = context.data;
  if (ctx.owner === null) return <p className={styles.noOwner}>{PROMOTION_COPY.noOwner}</p>;

  const nameValue = name ?? ctx.prefill.advertiser_legal_name ?? '';
  const emailValue = email ?? ctx.prefill.billing_email ?? '';
  const registryTrimmed = registry.trim();
  const invoiceTrimmed = invoice.trim();
  const nameError = nameValue.trim() ? null : PROMOTION_COPY.nameRequired;
  const registryError =
    registryTrimmed && !PROMOTION_REGISTRY_CODE_RE.test(registryTrimmed) ? PROMOTION_COPY.registryInvalid : null;
  const invoiceError =
    !complimentary && invoiceTrimmed && !invoiceTrimmed.startsWith(PROMOTION_INVOICE_PREFIX)
      ? PROMOTION_COPY.invoiceInvalid
      : null;
  const noteError = complimentary && !note.trim() ? PROMOTION_COPY.noteRequired : null;
  // null = not assessed yet; "none" = clear; any other tag needs a clearance (#612).
  const restriction = request ? request.promotion_restriction : ctx.promotion_restriction;
  const restrictionLabel = restrictionTag(restriction);
  const clearanceError = restrictionLabel === null
    ? null
    : !cleared
      ? REQUEST_COPY.clearanceAckRequired
      : !clearNote.trim()
        ? REQUEST_COPY.clearanceNoteRequired
        : null;

  // The server answers for the dates in view; while the next answer loads
  // (keepPreviousData) the previous one would be for other dates.
  const result = datesPicked ? validation.data : undefined;
  const checking = datesPicked && (validation.isFetching || validation.isPlaceholderData);
  const serverErrors = !checking && result ? result.errors : [];
  const startInvalid = serverErrors.some((e) => PROMOTION_ERROR_START_CODES.has(e.code));
  const endInvalid = serverErrors.length > 0 && !startInvalid;
  const datesOk = datesPicked && !checking && result?.valid === true;
  const canSubmit =
    datesOk &&
    !nameError &&
    PROMOTION_REGISTRY_CODE_RE.test(registryTrimmed) &&
    !invoiceError &&
    !noteError &&
    !clearanceError &&
    !grant.isPending;

  let message: { text: string; tone: 'error' | 'ok' | 'hint' };
  if (!datesPicked) message = { text: PROMOTION_COPY.pickDates, tone: 'hint' };
  else if (validation.isError) message = { text: ADMIN_GENERIC_ERROR, tone: 'error' };
  else if (checking || !result) message = { text: PROMOTION_COPY.checking, tone: 'hint' };
  else if (serverErrors.length > 0) message = { text: serverErrors[0].message, tone: 'error' };
  else message = { text: PROMOTION_COPY.datesAvailable, tone: 'ok' };

  const days = result?.days ?? 0;
  const pricing = ctx.pricing;
  const priceText = !result || !datesOk
    ? '—'
    : complimentary
      ? PROMOTION_COPY.complimentaryPrice
      : priceLine(result.price);
  const priceDetail =
    datesOk && result
      ? complimentary
        ? `${days} days × ${formatEuro(0)} net · VAT n/a`
        : `${days} days × ${formatEuro(pricing.day_price_cents)} net · VAT ${Number(pricing.vat_rate_percent)}%`
      : `${ctx.rules.min_days}–${ctx.rules.max_days} days · earliest start ${formatDay(ctx.earliest_start)} · event ends ${formatDay(ctx.event_last_day)}`;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    grant.mutate({
      start_date: start,
      end_date: end,
      advertiser_legal_name: nameValue.trim(),
      advertiser_registry_code: registryTrimmed,
      billing_email: emailValue.trim() || null,
      is_complimentary: complimentary,
      complimentary_note: complimentary ? note.trim() : null,
      invoice_reference: !complimentary && invoiceTrimmed ? invoiceTrimmed : null,
      ...(restrictionLabel !== null
        ? { restriction_clearance_confirmed: true, restriction_clearance_note: clearNote.trim() }
        : {}),
    });
  }

  const selected = datesPicked && end >= start ? { start, end } : null;

  return (
    <div className={styles.wrap}>
      {strip.data && !request && <PromotionCapStrip days={strip.data.days} todayIso={strip.data.today} selected={selected} />}
      <form className={styles.form} onSubmit={submit} noValidate>
        <div className={styles.event}>
          <strong>{ctx.event_title}</strong>
          {request && restrictionLabel !== null && <> <span className={styles.tag}>{restrictionLabel}</span></>}
          {request ? (
            <div className={styles.hint}>
              {REQUEST_COPY.requestedBy} {request.organizer_name} for {formatWindow(request.start_date, request.end_date)} · event ends{' '}
              {formatDay(ctx.event_last_day)}
            </div>
          ) : (
            <>
              <span className={styles.hint}> · ends {formatDay(ctx.event_last_day)}</span>
              <div className={styles.hint}>Owner: {ctx.owner.name}</div>
            </>
          )}
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${ids}-start`}>Start date</label>
          <DatePicker
            id={`${ids}-start`}
            ariaLabel="Start date"
            locale={ADMIN_LOCALE}
            dateOnly
            required
            value={start}
            min={ctx.earliest_start}
            max={ctx.event_last_day}
            isDayDisabled={(iso) => fullDays.has(iso)}
            invalid={startInvalid}
            onChange={setStart}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${ids}-end`}>End date</label>
          <DatePicker
            id={`${ids}-end`}
            ariaLabel="End date"
            locale={ADMIN_LOCALE}
            dateOnly
            required
            value={end}
            min={ctx.earliest_start}
            max={ctx.event_last_day}
            isDayDisabled={(iso) => fullDays.has(iso)}
            invalid={endInvalid}
            onChange={setEnd}
          />
        </div>
        <div className={styles.wide}>
          <div
            className={message.tone === 'error' ? styles.msgError : message.tone === 'ok' ? styles.msgOk : styles.msgHint}
            role="status"
            aria-live="polite"
          >
            {message.text}
          </div>
          {request && datesPicked && (
            <div className={styles.msgHint}>
              {start === request.start_date && end === request.end_date
                ? REQUEST_COPY.datesMatch
                : REQUEST_COPY.datesDiffer(formatWindow(request.start_date, request.end_date))}
            </div>
          )}
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${ids}-name`}>Advertiser legal name</label>
          <input
            id={`${ids}-name`}
            className={styles.input}
            value={nameValue}
            aria-invalid={nameError ? true : undefined}
            onChange={(e) => setName(e.target.value)}
          />
          {nameError && <span className={styles.fieldError}>{nameError}</span>}
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${ids}-registry`}>Registry code</label>
          <input
            id={`${ids}-registry`}
            className={`${styles.input} ${styles.mono}`}
            inputMode="numeric"
            value={registry}
            aria-invalid={registryError ? true : undefined}
            onChange={(e) => setRegistry(e.target.value)}
          />
          {registryError && <span className={styles.fieldError}>{registryError}</span>}
        </div>
        {!complimentary && (
          <div className={styles.field}>
            <label className={styles.label} htmlFor={`${ids}-invoice`}>Invoice reference</label>
            <input
              id={`${ids}-invoice`}
              className={`${styles.input} ${styles.mono}`}
              placeholder={`${PROMOTION_INVOICE_PREFIX}0001`}
              value={invoice}
              aria-invalid={invoiceError ? true : undefined}
              onChange={(e) => setInvoice(e.target.value)}
            />
            {invoiceError && <span className={styles.fieldError}>{invoiceError}</span>}
          </div>
        )}
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${ids}-email`}>Billing email</label>
          <input
            id={`${ids}-email`}
            className={styles.input}
            type="email"
            value={emailValue}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        <div className={styles.check}>
          <input
            id={`${ids}-comp`}
            type="checkbox"
            checked={complimentary}
            onChange={(e) => setComplimentary(e.target.checked)}
          />
          <label htmlFor={`${ids}-comp`}>Complimentary (€0)</label>
        </div>
        {complimentary && (
          <div className={styles.wide}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`${ids}-note`}>Note (required)</label>
              <textarea
                id={`${ids}-note`}
                className={styles.input}
                rows={PROMOTION_NOTE_ROWS}
                placeholder="Why is this free?"
                value={note}
                aria-invalid={noteError ? true : undefined}
                onChange={(e) => setNote(e.target.value)}
              />
              {noteError && <span className={styles.fieldError}>{noteError}</span>}
            </div>
          </div>
        )}

        {restrictionLabel !== null && (
          <div className={`${styles.alert} ${styles.wide}`}>
            <div className={styles.alertTitle}>{REQUEST_COPY.restrictionTitle(restrictionLabel.toLowerCase())}</div>
            <div>{REQUEST_COPY.restrictionBody}</div>
            <div className={styles.clearAck}>
              <input
                id={`${ids}-clear`}
                type="checkbox"
                checked={cleared}
                onChange={(e) => setCleared(e.target.checked)}
              />
              <label htmlFor={`${ids}-clear`}>{REQUEST_COPY.clearanceAck}</label>
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor={`${ids}-clearnote`}>{REQUEST_COPY.clearanceNoteLabel}</label>
              <textarea
                id={`${ids}-clearnote`}
                className={styles.input}
                rows={PROMOTION_NOTE_ROWS}
                value={clearNote}
                onChange={(e) => setClearNote(e.target.value)}
              />
            </div>
          </div>
        )}
        {restriction === null && (
          <div className={`${styles.alert} ${styles.wide}`}>
            <div className={styles.alertTitle}>{REQUEST_COPY.unassessedTitle}</div>
            <div>{REQUEST_COPY.unassessedBody}</div>
          </div>
        )}

        <div className={styles.price}>
          <div>
            <span className={styles.mono}>{priceText}</span>
            <div className={styles.hint}>{priceDetail}</div>
          </div>
          <div className={styles.buttons}>
            <button type="submit" className={styles.submit} disabled={!canSubmit}>
              {PROMOTION_COPY.grantHeading}
            </button>
            {request && (
              <button type="button" className={styles.cancel} onClick={onCancel}>
                Cancel
              </button>
            )}
          </div>
        </div>
        {request && <p className={`${styles.hint} ${styles.wide}`}>{REQUEST_COPY.grantNote}</p>}
      </form>
    </div>
  );
}
