import { StatusCodes } from 'http-status-codes';
import { useEffect, useId, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, organizerApi } from '../../api/client';
import DatePicker from '../../components/DatePicker';
import EventCard, { type EventData } from '../../components/EventCard';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import PageState from '../../components/PageState';
import PromotionResultCard from '../../components/PromotionResultCard';
import SeoTags from '../../components/SeoTags';
import { API, QUERY_KEYS } from '../../constants/api';
import { UI_STATE } from '../../constants/core';
import {
  PROMOTION_CHECKOUT_CODE,
  PROMOTION_CHECKOUT_HOLD_MINUTES,
  PROMOTION_ERROR_CAP_EXCEEDED,
  PROMOTION_ERROR_TOO_LONG,
  PROMOTION_ERROR_TOO_SHORT,
  PROMOTION_FORM_ERROR_KEYS,
  PROMOTION_FORM_EVENT_PARAM,
  PROMOTION_LEGAL_NAME_MAX_LEN,
  PROMOTION_MAX_DAYS,
  PROMOTION_NOTE_MAX_LEN,
  PROMOTION_NOTE_ROWS,
  PROMOTION_REGISTRY_CODE,
  PROMOTION_REGISTRY_CODE_LENGTH,
} from '../../constants/organizerPromotions';
import { ROUTES } from '../../constants/routes';
import { useEventCardNav } from '../../hooks/useEventCardNav';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { t, ti } from '../../i18n';
import {
  formatMoney,
  formatPromoDay,
  formatPromoDays,
  formatPromoRange,
  isIsoDay,
  isRegistryCodeValid,
  splitAround,
  type CheckoutStarted,
  type PromotionRequestContext,
  type PromotionRequestCreated,
  type PromotionValidation,
  type RegistryLookupResult,
} from '../../lib/organizerPromotions';
import { addDays, cx, formatEventTime, parseISODateLocal, toDateStr, withLocaleQuery } from '../../utils';
import CheckRow from './CheckRow';
import styles from './OrganizerPromotionRequest.module.css';

type LookupState = 'idle' | 'invalid' | 'busy' | 'found' | 'deleted' | 'notFound' | 'outage';
type CardBlock = 'review' | 'unavailable' | null;

const LOOKUP_MESSAGE: Record<Exclude<LookupState, 'idle'>, { tone: string; key: string }> = {
  busy: { tone: styles.lookupMute, key: 'promo_lookup_busy' },
  found: { tone: styles.lookupOk, key: 'promo_lookup_found' },
  invalid: { tone: styles.lookupBad, key: 'promo_lookup_invalid' },
  deleted: { tone: styles.lookupBad, key: 'promo_lookup_deleted' },
  notFound: { tone: styles.lookupBad, key: 'promo_lookup_not_found' },
  outage: { tone: styles.lookupWarn, key: 'promo_lookup_outage' },
};

/** The first rule the server refused, worded in the viewer's language. */
function dateErrorMessage(validation: PromotionValidation, context: PromotionRequestContext, locale: string): string {
  const error = validation.errors[0];
  if (error.code === PROMOTION_ERROR_TOO_SHORT || error.code === PROMOTION_ERROR_TOO_LONG) {
    return ti('promo_err_len', locale, { days: formatPromoDays(validation.days, locale) });
  }
  if (error.code === PROMOTION_ERROR_CAP_EXCEEDED) {
    const day = error.dates[0];
    return day
      ? ti('promo_err_full', locale, { date: formatPromoDay(day, locale) })
      : t('promo_err_full_any', locale);
  }
  if (error.code === 'ends_after_event') {
    return ti('promo_err_end', locale, { date: formatPromoDay(context.event_last_day, locale) });
  }
  const key = PROMOTION_FORM_ERROR_KEYS[error.code];
  return key ? t(key, locale) : t('generic_error', locale);
}

/** A failed submit, worded in the viewer's language. */
function submitErrorMessage(err: unknown, locale: string): string {
  if (err instanceof ApiError) {
    if (err.code === PROMOTION_CHECKOUT_CODE.provider) return t('promo_err_checkout', locale);
    if (err.code === PROMOTION_ERROR_CAP_EXCEEDED) return t('promo_err_full_any', locale);
    const key = err.code ? PROMOTION_FORM_ERROR_KEYS[err.code] : undefined;
    if (key) return t(key, locale);
    if (err.code === 'network_error') return err.message;
  }
  return t('generic_error', locale);
}

/** Request form (#614, #617, #618): one event, a window, a business, and either
 * a card payment or a request an admin grants and invoices. A live EventCard
 * preview and the price sit beside the fields. */
export default function OrganizerPromotionRequest() {
  const [locale, handleLocaleChange] = useLocalLocale();
  const localePath = useLocalePath();
  const handleLogout = useOrganizerLogout();
  const queryClient = useQueryClient();
  const cardNav = useEventCardNav();
  const seoMeta = useStaticSeoMeta('promo_form_eyebrow', locale);
  const [searchParams] = useSearchParams();
  const eventId = Number(searchParams.get(PROMOTION_FORM_EVENT_PARAM));
  const ids = useId();

  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [code, setCode] = useState('');
  const [legal, setLegal] = useState('');
  const [email, setEmail] = useState('');
  const [note, setNote] = useState('');
  const [terms, setTerms] = useState(false);
  const [policy, setPolicy] = useState(false);
  const [mode, setMode] = useState<'card' | 'request'>('card');
  const [failedBlock, setCardBlock] = useState<CardBlock>(null);
  const [registryDown, setRegistryDown] = useState(false);
  const [tried, setTried] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [sent, setSent] = useState<PromotionRequestCreated | null>(null);

  const context = useQuery({
    queryKey: [QUERY_KEYS.organizerPromotionContext, eventId],
    queryFn: () => organizerApi.get<PromotionRequestContext>(`${API.organizerPromotionContext}?event_id=${eventId}`),
    enabled: eventId > 0,
    retry: false,
  });
  const ctx = context.data;
  // The context says up front whether card checkout is open for this event; a
  // refusal at submit (a stale context) still lands on the same request path.
  const ctxBlock: CardBlock = ctx?.review_required ? 'review' : ctx && !ctx.checkout_available ? 'unavailable' : null;
  const cardBlock = ctxBlock ?? failedBlock;

  const eventQuery = useQuery({
    queryKey: [QUERY_KEYS.organizerPromotionEvent, eventId, locale],
    queryFn: () => api.get<EventData>(withLocaleQuery(API.event(eventId), locale)),
    enabled: ctx?.promotable === true,
    retry: false,
  });

  // Dates are validated by the server (window, overlap, sold-out days), so the
  // form carries no copy of those rules; the picker only greys days it knows.
  const datesPicked = isIsoDay(start) && isIsoDay(end);
  const validation = useQuery({
    queryKey: [QUERY_KEYS.organizerPromotionValidate, eventId, start, end],
    queryFn: () =>
      organizerApi.get<PromotionValidation>(
        `${API.organizerPromotionValidate}?event_id=${eventId}&start_date=${start}&end_date=${end}`,
      ),
    enabled: ctx?.promotable === true && datesPicked,
    placeholderData: keepPreviousData,
    retry: false,
  });
  const checking = datesPicked && (validation.isFetching || validation.isPlaceholderData);
  const result = datesPicked && !checking ? validation.data : undefined;
  const datesOk = result?.valid === true;
  const dateError = ctx && result && !result.valid ? dateErrorMessage(result, ctx, locale) : null;

  const codeReady = code.length === PROMOTION_REGISTRY_CODE_LENGTH && isRegistryCodeValid(code);
  const lookup = useQuery({
    queryKey: [QUERY_KEYS.organizerPromotionRegistry, code],
    queryFn: () => organizerApi.post<RegistryLookupResult>(API.organizerPromotionRegistryLookup, { registry_code: code }),
    enabled: ctx?.promotable === true && codeReady && !registryDown,
    retry: false,
    staleTime: Infinity,
  });

  let lookupState: LookupState = 'idle';
  if (registryDown && codeReady) lookupState = 'outage';
  else if (code.length === PROMOTION_REGISTRY_CODE_LENGTH && !codeReady) lookupState = 'invalid';
  else if (codeReady && lookup.isFetching) lookupState = 'busy';
  else if (codeReady && lookup.data) lookupState = 'found';
  else if (codeReady && lookup.error) {
    const refusal = lookup.error instanceof ApiError ? lookup.error.code : undefined;
    lookupState =
      refusal === PROMOTION_REGISTRY_CODE.deleted
        ? 'deleted'
        : refusal === PROMOTION_REGISTRY_CODE.notFound
          ? 'notFound'
          : refusal === PROMOTION_REGISTRY_CODE.invalid
            ? 'invalid'
            : 'outage';
  }

  const registryName = lookupState === 'found' ? (lookup.data?.legal_name ?? '') : null;
  const legalValue = registryName ?? legal;
  const outage = lookupState === 'outage';
  const wantsCard = cardBlock === null && !outage && mode === 'card';
  const registryOk = lookupState === 'found' || (outage && codeReady && legal.trim().length > 1);

  const problems: string[] = [];
  if (!datesPicked) problems.push(t('promo_err_need_dates', locale));
  else if (dateError) problems.push(dateError);
  else if (!datesOk) problems.push(t('promo_err_need_dates', locale));
  if (!registryOk) problems.push(t(outage ? 'promo_need_legal' : 'promo_need_code', locale));
  if (!terms) problems.push(t('promo_need_terms', locale));
  if (wantsCard && !policy) problems.push(t('promo_need_policy', locale));

  const billingEmail = email.trim();
  const checkout = useMutation({
    mutationFn: () =>
      organizerApi.post<CheckoutStarted>(API.organizerPromotionCheckout, {
        event_id: eventId,
        start_date: start,
        end_date: end,
        registry_code: code,
        billing_email: billingEmail || null,
        content_policy_attested: policy,
        terms_accepted: terms,
      }),
    // The browser leaves for Stripe's hosted page; it comes back to the success route.
    onSuccess: (started) => window.location.assign(started.checkout_url),
    onError: (err) => {
      if (err instanceof ApiError) {
        if (err.code === PROMOTION_CHECKOUT_CODE.needsReview) {
          setCardBlock('review');
          setSubmitError(null);
          return;
        }
        if (err.status === StatusCodes.NOT_FOUND) {
          // Card checkout is off: the offer is on, so a request is still open.
          setCardBlock('unavailable');
          setSubmitError(null);
          return;
        }
        if (err.code === PROMOTION_REGISTRY_CODE.unavailable) {
          setRegistryDown(true);
          setSubmitError(null);
          return;
        }
      }
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerPromotionValidate, eventId] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerPromotionContext, eventId] });
      setSubmitError(submitErrorMessage(err, locale));
    },
  });

  const sendRequest = useMutation({
    mutationFn: () =>
      organizerApi.post<PromotionRequestCreated>(API.organizerPromotionRequests, {
        event_id: eventId,
        start_date: start,
        end_date: end,
        advertiser_legal_name: legalValue.trim(),
        advertiser_registry_code: code,
        billing_email: billingEmail || null,
        note: note.trim() || null,
        terms_accepted: terms,
      }),
    onSuccess: (created) => {
      setSent(created);
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerPromotions] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerEvents] });
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerClaimEvents] });
      window.scrollTo(0, 0);
    },
    onError: (err) => {
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerPromotionValidate, eventId] });
      setSubmitError(submitErrorMessage(err, locale));
    },
  });
  const submitting = checkout.isPending || sendRequest.isPending;

  // A Stripe session that was opened but not paid leaves the page behind in
  // bfcache; coming back must not show a stuck "Opening…" button.
  useEffect(() => {
    const reset = (e: PageTransitionEvent) => {
      if (e.persisted) checkout.reset();
    };
    window.addEventListener('pageshow', reset);
    return () => window.removeEventListener('pageshow', reset);
  }, [checkout]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setTried(true);
    setSubmitError(null);
    if (problems.length > 0) return;
    if (wantsCard) checkout.mutate();
    else sendRequest.mutate();
  }

  function handleStart(value: string) {
    setStart(value);
    if (value && end && (end < value || end > toDateStr(addDays(parseISODateLocal(value), PROMOTION_MAX_DAYS - 1)))) {
      setEnd('');
    }
  }

  const topBar = <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />;
  const backLink = (
    <Link to={localePath(ROUTES.organizerDashboard)} className={styles.back}>
      ← {t('promo_back', locale)}
    </Link>
  );

  if (eventId <= 0 || context.isError || (ctx && !ctx.promotable)) {
    return (
      <div className={styles.page}>
        <SeoTags meta={seoMeta} />
        {topBar}
        <main className={styles.main}>
          {backLink}
          <div className={styles.unavailable}>
            <h1 className={styles.heading}>{t('promo_form_unavailable_title', locale)}</h1>
            <p className={styles.sub}>{t('promo_form_unavailable_msg', locale)}</p>
          </div>
        </main>
      </div>
    );
  }
  if (!ctx) {
    return (
      <div className={styles.page}>
        <SeoTags meta={seoMeta} />
        {topBar}
        <main className={styles.main}>
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        </main>
      </div>
    );
  }

  if (sent) {
    return (
      <div className={styles.page}>
        <SeoTags meta={seoMeta} />
        {topBar}
        <main className={styles.main}>
          <PromotionResultCard
            icon="check"
            live
            title={t('promo_sent_title', locale)}
            message={t('promo_sent_msg', locale)}
            recap={[
              { label: t('promo_recap_event', locale), value: sent.event_title },
              {
                label: t('promo_recap_window', locale),
                value: `${formatPromoRange(sent.start_date, sent.end_date, locale)} · ${formatPromoDays(sent.days, locale)}`,
              },
              { label: t('promo_recap_advertiser', locale), value: sent.advertiser_legal_name },
              { label: t('promo_recap_total', locale), value: formatMoney(sent.price.gross_cents, locale) },
            ]}
            links={[
              { to: localePath(ROUTES.organizerPromotions), label: t('promo_view', locale), primary: true },
              { to: localePath(ROUTES.organizerDashboard), label: t('promo_to_events', locale) },
            ]}
          />
        </main>
      </div>
    );
  }

  const price = result?.valid ? result.price : null;
  const dayGross = Math.round((ctx.pricing.day_price_cents * (100 + Number(ctx.pricing.vat_rate_percent))) / 100);
  const [termsBefore, termsAfter] = splitAround(
    ti('promo_terms_label', locale, { version: String(ctx.terms_version), link: '{link}' }),
    'link',
  );
  const [policyBefore, policyAfter] = splitAround(t('promo_policy_label', locale), 'link');
  const eventData = eventQuery.data;
  const advertiser = legalValue.trim() || t('promo_your_business', locale);
  const payAmount = price ? formatMoney(price.gross_cents, locale).slice(1) : '…';
  const primaryLabel = wantsCard
    ? ti('promo_pay', locale, { amount: payAmount })
    : t('promo_send_request', locale);
  const lookupMessage = lookupState === 'idle' ? null : LOOKUP_MESSAGE[lookupState];
  const codeInvalid = lookupState === 'invalid' || lookupState === 'deleted' || lookupState === 'notFound' || (tried && !registryOk && !outage);
  const startInvalid = tried && !isIsoDay(start);
  const endInvalid = (tried && !isIsoDay(end)) || (datesPicked && Boolean(dateError));
  const unavailableDays = new Set(ctx.unavailable_dates);
  const startMax = ctx.event_last_day;
  const endMax =
    start && isIsoDay(start)
      ? (() => {
          const furthest = toDateStr(addDays(parseISODateLocal(start), PROMOTION_MAX_DAYS - 1));
          return furthest < ctx.event_last_day ? furthest : ctx.event_last_day;
        })()
      : ctx.event_last_day;

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      {topBar}
      <main className={cx(styles.main, styles.mainWide)}>
        {backLink}
        <header className={styles.masthead}>
          <p className={styles.eyebrow}>{t('promo_form_eyebrow', locale)}</p>
          <h1 className={styles.heading}>{ti('promo_form_title', locale, { title: ctx.event_title })}</h1>
          <p className={styles.sub}>{t('promo_form_sub', locale)}</p>
        </header>

        <form className={styles.formGrid} onSubmit={handleSubmit} noValidate>
          <div className={styles.fields}>
            {cardBlock === 'review' && (
              <div className={styles.notice} role="status">
                <strong>{t('promo_review_title', locale)}</strong>
                <span>{t('promo_review_msg', locale)}</span>
              </div>
            )}
            {cardBlock === 'unavailable' && (
              <div className={styles.notice} role="status">
                <span>{t('promo_card_unavailable', locale)}</span>
              </div>
            )}
            {outage && (
              <div className={styles.notice} role="status">
                <strong>{t('promo_outage_title', locale)}</strong>
                <span>{t('promo_outage_msg', locale)}</span>
              </div>
            )}

            <div className={styles.group}>
              <span className={styles.label}>{t('promo_form_event', locale)}</span>
              <div className={styles.fixedEvent}>
                <span className={styles.fixedTitle}>{ctx.event_title}</span>
                {eventData && (
                  <span className={styles.rowMeta}>
                    {formatEventTime(eventData.starts_at, locale)}
                    {eventData.venue_name ? ` · ${eventData.venue_name}` : ''}
                  </span>
                )}
                <span className={styles.fixedNote}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                    <rect x="5" y="11" width="14" height="9" rx="1" />
                    <path d="M8 11V8a4 4 0 018 0v3" />
                  </svg>
                  {t('promo_form_event_note', locale)}
                </span>
              </div>
            </div>

            <div className={styles.group}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldCol}>
                  <label className={styles.label} htmlFor={`${ids}-start`}>{t('promo_start_date', locale)}</label>
                  <DatePicker
                    id={`${ids}-start`}
                    dateOnly
                    value={start}
                    onChange={handleStart}
                    locale={locale}
                    min={ctx.earliest_start}
                    max={startMax}
                    isDayDisabled={(day) => unavailableDays.has(day)}
                    invalid={startInvalid}
                    ariaLabel={t('promo_start_date', locale)}
                  />
                </div>
                <div className={styles.fieldCol}>
                  <label className={styles.label} htmlFor={`${ids}-end`}>{t('promo_end_date', locale)}</label>
                  <DatePicker
                    id={`${ids}-end`}
                    dateOnly
                    value={end}
                    onChange={setEnd}
                    locale={locale}
                    min={start && isIsoDay(start) ? start : ctx.earliest_start}
                    max={endMax}
                    isDayDisabled={(day) => unavailableDays.has(day)}
                    invalid={endInvalid}
                    ariaLabel={t('promo_end_date', locale)}
                  />
                </div>
              </div>
              {(tried || datesPicked) && dateError && (
                <p className={styles.err} role="alert">{dateError}</p>
              )}
              {tried && !datesPicked && (
                <p className={styles.err} role="alert">{t('promo_err_need_dates', locale)}</p>
              )}
              {datesOk && result && (
                <p className={styles.windowRead}>
                  <span>{t('promo_window_read', locale)}:</span>
                  <b>{formatPromoRange(start, end, locale)}</b>
                  <span>{formatPromoDays(result.days, locale)}</span>
                </p>
              )}
              <p className={styles.hint}>
                {ti('promo_date_rules', locale, { date: formatPromoDay(ctx.event_last_day, locale) })}{' '}
                {t('promo_picker_hint', locale)}
              </p>
            </div>

            <div className={styles.group}>
              <div className={styles.fieldCol}>
                <label className={styles.label} htmlFor={`${ids}-code`}>{t('promo_reg_code', locale)}</label>
                <input
                  id={`${ids}-code`}
                  className={cx(styles.input, styles.mono, codeInvalid && styles.invalid)}
                  inputMode="numeric"
                  maxLength={PROMOTION_REGISTRY_CODE_LENGTH}
                  autoComplete="off"
                  placeholder="12345678"
                  value={code}
                  aria-invalid={codeInvalid || undefined}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, PROMOTION_REGISTRY_CODE_LENGTH))}
                />
                {lookupMessage ? (
                  <p className={cx(styles.lookup, lookupMessage.tone)} role="status">
                    {lookupState === 'busy' ? (
                      <span className={styles.spinner} aria-hidden="true" />
                    ) : (
                      <span aria-hidden="true">{lookupState === 'found' ? '✓' : '!'}</span>
                    )}
                    <span>{t(lookupMessage.key, locale)}</span>
                  </p>
                ) : (
                  <p className={styles.hint}>{t('promo_reg_hint', locale)}</p>
                )}
              </div>
              <div className={styles.fieldCol}>
                <label className={styles.label} htmlFor={`${ids}-legal`}>{t('promo_legal_name', locale)}</label>
                {registryName !== null ? (
                  <div className={styles.lockWrap}>
                    <input
                      id={`${ids}-legal`}
                      className={styles.input}
                      value={registryName}
                      readOnly
                      aria-describedby={`${ids}-legal-hint`}
                    />
                    <svg className={styles.lockIcon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
                      <rect x="5" y="11" width="14" height="9" rx="1" />
                      <path d="M8 11V8a4 4 0 018 0v3" />
                    </svg>
                  </div>
                ) : (
                  <input
                    id={`${ids}-legal`}
                    className={styles.input}
                    value={legal}
                    maxLength={PROMOTION_LEGAL_NAME_MAX_LEN}
                    autoComplete="organization"
                    placeholder={t('promo_legal_placeholder', locale)}
                    aria-describedby={`${ids}-legal-hint`}
                    onChange={(e) => setLegal(e.target.value)}
                  />
                )}
                <p className={styles.hint} id={`${ids}-legal-hint`}>
                  {t(registryName !== null ? 'promo_legal_from_register' : 'promo_legal_hint', locale)}
                </p>
              </div>
            </div>

            <div className={styles.group}>
              <div className={styles.fieldCol}>
                <label className={styles.label} htmlFor={`${ids}-email`}>
                  {t('promo_billing_email', locale)}{' '}
                  <span className={styles.optional}>({t('promo_optional', locale)})</span>
                </label>
                <input
                  id={`${ids}-email`}
                  className={styles.input}
                  type="email"
                  autoComplete="email"
                  placeholder={ctx.billing_email_default}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
                <p className={styles.hint}>{ti('promo_billing_hint', locale, { email: ctx.billing_email_default })}</p>
              </div>
              {!wantsCard && (
                <div className={styles.fieldCol}>
                  <label className={styles.label} htmlFor={`${ids}-note`}>
                    {t('promo_note', locale)}{' '}
                    <span className={styles.optional}>({t('promo_optional', locale)})</span>
                  </label>
                  <textarea
                    id={`${ids}-note`}
                    className={cx(styles.input, styles.textarea)}
                    rows={PROMOTION_NOTE_ROWS}
                    maxLength={PROMOTION_NOTE_MAX_LEN}
                    placeholder={t('promo_note_placeholder', locale)}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </div>
              )}
            </div>
          </div>

          <aside className={styles.summary} aria-label={t('promo_summary_title', locale)}>
            <h2 className={styles.eyebrowSm}>{t('promo_summary_title', locale)}</h2>
            {eventData ? (
              <EventCard
                event={eventData}
                index={0}
                locale={locale}
                nav={cardNav}
                readOnly
                sponsored={{ advertiser, explanation: 'none' }}
              />
            ) : eventQuery.isError ? (
              <PageState kind={UI_STATE.error} message={t('promo_event_load_error', locale)} inline />
            ) : (
              <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
            )}
            <div className={styles.ledger}>
              <span className={styles.eyebrowSm}>{t('promo_price_head', locale)}</span>
              <span className={styles.priceLine}>
                {ti('promo_price_per_day', locale, {
                  net: formatMoney(ctx.pricing.day_price_cents, locale),
                  gross: formatMoney(dayGross, locale),
                })}
              </span>
              <span className={cx(styles.eyebrowSm, styles.totalHead)}>{t('promo_total_head', locale)}</span>
              {price && result ? (
                <>
                  <span className={styles.total} aria-live="polite">
                    {ti('promo_total_line', locale, {
                      net: formatMoney(price.net_cents, locale),
                      vat: formatMoney(price.vat_cents, locale),
                      total: formatMoney(price.gross_cents, locale),
                    })}
                  </span>
                  <span className={styles.hint}>
                    {formatPromoDays(result.days, locale)} · {formatPromoRange(start, end, locale)}
                  </span>
                </>
              ) : (
                <span className={cx(styles.total, styles.totalMuted)}>{t('promo_total_none', locale)}</span>
              )}
            </div>
            <div className={styles.promise}>
              <strong>{t('promo_promise_1', locale)}</strong>
              <span>{t('promo_promise_2', locale)}</span>
            </div>
          </aside>

          <div className={styles.actionsBox}>
            {wantsCard && (
              <CheckRow id={`${ids}-policy`} checked={policy} onChange={setPolicy} invalid={tried && !policy}>
                {policyBefore}
                <Link to={localePath(ROUTES.organizerContentPolicy)}>{t('promo_policy_link', locale)}</Link>
                {policyAfter}
              </CheckRow>
            )}
            <CheckRow id={`${ids}-terms`} checked={terms} onChange={setTerms} invalid={tried && !terms}>
              {termsBefore}
              <Link to={localePath(ROUTES.organizerTerms)}>{t('promo_terms_link', locale)}</Link>
              {termsAfter}
            </CheckRow>
            {tried && problems.length > 0 && (
              <p className={styles.err} role="alert">
                {t('promo_fix_errors', locale)} {problems[0]}
              </p>
            )}
            {submitError && (
              <p className={styles.err} role="alert">{submitError}</p>
            )}
            <button type="submit" className={styles.submit} disabled={submitting}>
              {checkout.isPending ? (
                <>
                  <span className={cx(styles.spinner, styles.onAccent)} aria-hidden="true" />
                  {t('promo_opening', locale)}
                </>
              ) : (
                primaryLabel
              )}
            </button>
            {wantsCard && (
              <button type="button" className={styles.textButton} onClick={() => setMode('request')}>
                {t('promo_pay_bank', locale)}
              </button>
            )}
            {!wantsCard && cardBlock === null && !outage && (
              <button type="button" className={styles.textButton} onClick={() => setMode('card')}>
                {t('promo_pay_card', locale)}
              </button>
            )}
            <p className={styles.small}>
              {wantsCard
                ? ti('promo_hold_note', locale, { minutes: String(PROMOTION_CHECKOUT_HOLD_MINUTES) })
                : t('promo_request_note', locale)}
            </p>
          </div>
        </form>
      </main>
    </div>
  );
}
