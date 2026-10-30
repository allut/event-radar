import { Fragment, memo, useMemo, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { CATEGORIES, LOCALES, MAGIC_LINK_EXPIRY_MINUTES } from '../../_generated/sharedConstants';
import { API, QUERY_KEYS } from '../../constants/api';
import {
  ACCENT_MARKER_RE,
  COPYRIGHT_YEAR,
  EUR_SYMBOL,
  LANDING_BASE_FIG_COUNT,
  LANDING_PLATE_BODY_MAX_LENGTH,
  LANDING_SHOWCASE_PLATE_COUNT,
  STEP_KEYS,
  UI_STATE,
} from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import { OG_FALLBACK_IMAGE_PATH, PRODUCTION_ORIGIN } from '../../constants/seo';
import { t, ti } from '../../i18n';
import { categoryGradient, cx, formatCount, formatEventTime, formatHeroDateline, formatHourMinute, formatPrice, padIndex, safeUrl, stripHtmlToText, truncateForMeta, withLocaleQuery } from '../../utils';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useMagicLinkRequest } from '../../hooks/useMagicLinkRequest';
import { useOrganizerAuth } from '../../hooks/useOrganizerAuth';
import { usePrefersReducedMotion } from '../../hooks/usePrefersReducedMotion';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import { buildWebsiteJsonLd } from '../../lib/structuredData';
import TopBar from '../../components/TopBar';
import SeoTags from '../../components/SeoTags';
import { type EventData } from '../../components/EventCard';
import animStyles from '../../components/shared/Animations.module.css';
import styles from './Landing.module.css';

interface ShowcaseResponse {
  events: EventData[];
}

interface TonightEvent {
  title: string;
  starts_at: string;
  venue_name: string | null;
}

interface CountsResponse {
  upcoming_count: number;
  venue_count: number;
  furthest_date: string | null;
  cheapest_price: number | null;
  today_count: number;
  tonight_is_fallback: boolean;
  tonight_events: TonightEvent[];
}

// Hoisted — constant across renders (Big-O audit #5, item 3.7).
const FOOTER_LOCALE_NAMES = LOCALES.map((l) => l.nativeName).join(' · ');

/** Renders an i18n template containing a single `{count}` placeholder with
 * just the count bolded, e.g. "1,008+ events on the radar right now". */
function CountSegment({ template, count }: { template: string; count: string }) {
  const [before, after] = template.split('{count}');
  return <>{before}<b>{count}</b>{after ?? ''}</>;
}

/** Renders an i18n string with an `_accented_` word wrapped in markup, e.g.
 * "…tasub kodust _välja_ minna." → "…tasub kodust <em>välja</em> minna."
 * No-op when the string carries no underscore markers. */
function AccentedText({ text }: { text: string }) {
  const parts = text.split(ACCENT_MARKER_RE);
  const seen = new Map<string, number>();
  return (
    <>
      {parts.map((part, i) => {
        const base = `${i % 2 === 1 ? 'a' : 't'}:${part}`;
        const occurrence = seen.get(base) ?? 0;
        seen.set(base, occurrence + 1);
        const key = occurrence === 0 ? base : `${base}#${occurrence}`;
        return i % 2 === 1 ? (
          <em key={key} className={styles.markAccent}>{part}</em>
        ) : (
          <Fragment key={key}>{part}</Fragment>
        );
      })}
    </>
  );
}

function EmailCapture({ locale }: { locale: string }) {
  const { email, setEmail, state, errorMsg, submit } = useMagicLinkRequest(locale);

  if (state === UI_STATE.success) {
    return (
      <div className={styles.success} role="status">
        <div className={styles.checkCircle} aria-hidden>✓</div>
        <p className={styles.successMsg}>
          {t('check_inbox', locale)} <strong>{email}</strong>
        </p>
        <p className={styles.successHint}>
          {ti('link_expires', locale, { minutes: String(MAGIC_LINK_EXPIRY_MINUTES) })}
        </p>
      </div>
    );
  }

  return (
    <>
      <form onSubmit={submit} className={styles.emailForm} noValidate>
        <input
          type="email"
          className={styles.input}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t('email_placeholder', locale)}
          autoComplete="email"
          disabled={state === UI_STATE.loading}
          aria-label={t('email_label', locale)}
          required
        />
        <button type="submit" className={styles.submit} disabled={state === UI_STATE.loading || !email.trim()}>
          {state === UI_STATE.loading
            ? <span className={styles.spinner} aria-label={t('sending', locale)} />
            : t('landing_cta_primary', locale)}
        </button>
        {state === UI_STATE.error && <p className={styles.error} role="alert">{errorMsg}</p>}
      </form>
      <p className={styles.fine}>{t('no_password', locale)}</p>
    </>
  );
}

function TickerRow({ event, locale }: { event: TonightEvent; locale: string }) {
  return (
    <span className={styles.tkItem}>
      <b>{formatHourMinute(event.starts_at, locale)}</b>
      {event.venue_name ? `${event.title} · ${event.venue_name}` : event.title}
    </span>
  );
}

// memo'd — the doubled `track` array (marquee duplication) was otherwise
// rebuilt on every unrelated Landing render (Big-O audit #5, item 3.7).
const Ticker = memo(function Ticker({ locale, events, isFallback }: { locale: string; events: TonightEvent[]; isFallback: boolean }) {
  const reducedMotion = usePrefersReducedMotion();
  if (events.length === 0) return null;

  const title = t(isFallback ? 'landing_ticker_title_fallback' : 'landing_ticker_title_tonight', locale);
  // Duplicated content is the standard seamless-marquee technique — skipped
  // under reduced motion so a frozen mid-loop marquee never shows two
  // overlapping copies (wayfinder #186). Each copy tagged 0/1 rather than
  // keyed by array index, since the same event appears once per copy.
  const track = reducedMotion
    ? events.map((event) => ({ event, copy: 0 }))
    : [...events.map((event) => ({ event, copy: 0 })), ...events.map((event) => ({ event, copy: 1 }))];

  return (
    <div className={styles.ticker} data-testid="ticker">
      <div className={styles.tk}>
        <span className={styles.tkLabel}>{title}</span>
        <div className={styles.tkView}>
          <div className={cx(styles.tkTrack, !reducedMotion && animStyles.tickerSlide)}>
            {track.map(({ event, copy }) => (
              <TickerRow key={`${copy}-${event.starts_at}-${event.title}`} event={event} locale={locale} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
});

// memo'd — sanitizes/truncates event.description (DOMPurify) on every
// render otherwise, on Landing's LCP path (Big-O audit #5, item 3.7).
const Plate = memo(function Plate({ event, index, locale }: { event: EventData; index: number; locale: string }) {
  const localePath = useLocalePath();
  const isFlipped = index % 2 === 1;
  const category = event.categories[0];
  const categoryLabel = category ? t(`category_${category}`, locale) : null;
  const eyebrow = [formatEventTime(event.starts_at, locale), categoryLabel].filter(Boolean).join(' · ');
  const price = formatPrice(event.price_min, event.price_max, event.currency, locale, event.has_free_tier);
  const imageUrl = safeUrl(event.image_url);

  return (
    <article className={cx(styles.plate, isFlipped && styles.plateFlip)}>
      <div className={styles.plateMedia}>
        {imageUrl ? (
          <>
            <img src={imageUrl} alt="" aria-hidden className={styles.plateBackdrop} loading="lazy" />
            <img src={imageUrl} alt={event.title} loading="lazy" className={styles.plateImg} />
          </>
        ) : (
          <div className={styles.platePlaceholder} style={{ background: categoryGradient(event.categories) }} />
        )}
      </div>
      <div className={styles.plateText}>
        <p className={styles.plateEyebrow}>{eyebrow}</p>
        <h2 className={styles.plateH2}>
          <Link to={localePath(ROUTES.eventDetail(event.id))} className={cx(styles.plateTitleLink, styles.plateStretched)}>
            {event.title}
          </Link>
        </h2>
        {event.description && (
          <p className={styles.plateBody}>{truncateForMeta(stripHtmlToText(event.description), LANDING_PLATE_BODY_MAX_LENGTH)}</p>
        )}
        <div className={cx(styles.hair, animStyles.hairlineDraw)} />
        <div className={styles.meta}>
          {event.venue_name && <span>{event.venue_name}</span>}
          {price && <span>{price}</span>}
          {categoryLabel && <span>{categoryLabel}</span>}
        </div>
      </div>
    </article>
  );
});

function Fig({ value, labelKey, locale }: { value: string; labelKey: string; locale: string }) {
  return (
    <div className={styles.fig}>
      <b className={styles.figValue}>{value}</b>
      <span className={styles.figLabel}>{t(labelKey, locale)}</span>
    </div>
  );
}

export default function Landing() {
  const { locale, handleLocaleChange, isPending: localePending } = useLocaleMutation({ publicRoute: true });
  const localePath = useLocalePath();
  const isOrganizer = useOrganizerAuth();
  const seoMeta = useSeoMeta({
    title: t('seo_landing_title', locale),
    locale,
    path: ROUTES.home,
    indexable: true,
    description: t('seo_landing_description', locale),
    image: `${PRODUCTION_ORIGIN}${OG_FALLBACK_IMAGE_PATH}`,
  });
  // Stable identity across renders — SeoTags is memo'd and internally
  // useMemo's on jsonLd's identity (Big-O audit #5, item 3.1); a fresh
  // object per render was defeating both.
  const jsonLd = useMemo(() => buildWebsiteJsonLd(locale), [locale]);

  const { data: showcaseData } = useQuery({
    queryKey: [QUERY_KEYS.showcase, locale],
    queryFn: () => api.get<ShowcaseResponse>(withLocaleQuery(API.publicShowcase, locale)),
    retry: false,
  });
  const plateEvents = (showcaseData?.events ?? []).slice(0, LANDING_SHOWCASE_PLATE_COUNT);

  const { data: counts } = useQuery({
    queryKey: [QUERY_KEYS.counts, locale],
    queryFn: () => api.get<CountsResponse>(withLocaleQuery(API.publicCounts, locale)),
    retry: false,
  });
  const tonightEvents = counts?.tonight_events ?? [];
  const furthestYear = counts?.furthest_date ? Number(counts.furthest_date.slice(0, 4)) : null;

  const brand = t('brand', locale);
  const brandSplitIdx = brand.lastIndexOf(' ');
  const brandPrefix = brandSplitIdx === -1 ? brand : brand.slice(0, brandSplitIdx);
  const brandLast = brandSplitIdx === -1 ? '' : brand.slice(brandSplitIdx + 1);

  const exploreHref = localePath(ROUTES.explore);

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} jsonLd={jsonLd} />
      <TopBar locale={locale} onLocaleChange={handleLocaleChange} authed={false} localeDisabled={localePending} transparent showPulse={false} />

      <main>
        <div className={styles.heroGroup}>
          <section className={styles.hero}>
            <div className={styles.poster}>
              <div className={cx(styles.posterImg, animStyles.posterDrift)} />
            </div>
            <div className={styles.scrim} />
            <div className={styles.frame} />

            <div className={styles.heroGrid}>
              <div className={styles.heroMain}>
                <div className={styles.heroTop}>
                  <span className={styles.mark}>
                    {brandPrefix} <em className={styles.markAccent}>{brandLast}</em>
                  </span>
                  {counts && (
                    <span className={styles.heroCounter}>
                      <span className={styles.heroCounterItem}>
                        <CountSegment template={t('landing_hero_counter', locale)} count={formatCount(counts.upcoming_count, locale)} />
                      </span>
                      <span className={styles.heroCounterItem}>
                        <CountSegment template={t('landing_hero_venues', locale)} count={formatCount(counts.venue_count, locale)} />
                      </span>
                      <span className={styles.heroCounterItem}>
                        <CountSegment template={t('landing_hero_tonight', locale)} count={String(tonightEvents.length)} />
                      </span>
                    </span>
                  )}
                </div>

                <div className={styles.heroBot}>
                  <p className={styles.dateline}>{formatHeroDateline(locale)} · {t('landing_hero_city', locale)}</p>
                  <h1 className={styles.h1}>
                    <span className={animStyles.heroRise}>
                      <span><AccentedText text={t('landing_hero_h1', locale)} /></span>
                    </span>
                  </h1>
                  <p className={styles.sub}>{t('landing_hero_sub', locale)}</p>
                  <div className={cx(styles.cutline, animStyles.hairlineDraw)} />

                  <div className={styles.capbar}>
                    <div className={styles.capbarCol}>
                      <span className={styles.capbarLabel}>{t('landing_capbar_email_label', locale)}</span>
                      <EmailCapture locale={locale} />
                    </div>
                    <div className={styles.capbarDivider} />
                    <div className={styles.capbarCol}>
                      <span className={styles.capbarLabel}>{t('landing_capbar_browse_label', locale)}</span>
                      <Link
                        to={exploreHref}
                        className={styles.capbarBrowse}
                      >
                        {t('landing_cta_explore', locale)}
                      </Link>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <Ticker locale={locale} events={tonightEvents} isFallback={counts?.tonight_is_fallback ?? false} />
        </div>

        <div className={styles.wrap}>
          <section className={styles.flat}>
            <div className={styles.flatHeader}>
              <div>
                <p className={styles.flatEyebrow}>{t('landing_how_title', locale)}</p>
                <h2 className={styles.flatTitle}>{t('landing_personas_title', locale)}</h2>
              </div>
              <p className={styles.flatSub}>{t('landing_personas_sub', locale)}</p>
            </div>

            <ol className={styles.steps}>
              {STEP_KEYS.map((step, i) => (
                <li key={step.title} className={styles.step}>
                  <span className={styles.stepNum} aria-hidden>{padIndex(i + 1)}</span>
                  <h3 className={styles.stepTitle}>{t(step.title, locale)}</h3>
                  <p className={styles.stepBody}>{t(step.body, locale)}</p>
                </li>
              ))}
            </ol>

            {counts && (
              <div
                className={styles.figs}
                style={{ '--fig-count': String(LANDING_BASE_FIG_COUNT + Number(furthestYear !== null) + Number(counts.cheapest_price !== null)) } as CSSProperties}
              >
                <Fig value={`${formatCount(counts.upcoming_count, locale)}+`} labelKey="landing_stat_upcoming" locale={locale} />
                <Fig value={`${formatCount(counts.venue_count, locale)}+`} labelKey="landing_stat_venues" locale={locale} />
                <Fig value={String(CATEGORIES.length)} labelKey="landing_stat_categories" locale={locale} />
                {furthestYear !== null && (
                  <Fig value={String(furthestYear)} labelKey="landing_stat_horizon" locale={locale} />
                )}
                {counts.cheapest_price !== null && (
                  <Fig value={`${EUR_SYMBOL}${counts.cheapest_price}`} labelKey="landing_stat_price" locale={locale} />
                )}
              </div>
            )}
          </section>
        </div>

        <div className={styles.wrap}>
          <div className={styles.plates}>
            {plateEvents.map((event, i) => (
              <Plate key={event.id} event={event} index={i} locale={locale} />
            ))}
          </div>

          {counts && (
            <Link
              to={exploreHref}
              className={styles.showcaseCta}
            >
              {ti('landing_showcase_cta', locale, { count: formatCount(counts.upcoming_count, locale) })}
            </Link>
          )}

          <section className={styles.organizer} aria-labelledby="organizer-cta">
            <div className={styles.organizerText}>
              <p className={styles.organizerEyebrow}>
                {t('landing_organizer_eyebrow', locale)}
              </p>
              <h3 id="organizer-cta" className={styles.organizerTitle}>{t('landing_organizer_title', locale)}</h3>
              <p className={styles.organizerBody}>{t('landing_organizer_body', locale)}</p>
            </div>
            <Link to={localePath(isOrganizer ? ROUTES.organizerDashboard : ROUTES.organizerLogin)} className={styles.organizerCta}>
              {t('landing_organizer_cta', locale)}
            </Link>
          </section>

          <footer className={styles.footer}>
            <span className={styles.trustItem}>{t('landing_trust_nopassword', locale)}</span>
            <span className={styles.trustItem}>{t('landing_trust_notracking', locale)}</span>
            <span className={styles.trustItem}>{t('landing_trust_free', locale)}</span>
            <span className={styles.footerLocales}>{FOOTER_LOCALE_NAMES}</span>
            <span className={styles.footerYear}>{t('brand', locale)}, {COPYRIGHT_YEAR}</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
