import { useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, organizerApi } from '../../api/client';
import { t, ti } from '../../i18n';
import { buildMapsUrl, categoryGradient, cx, formatEventDateTime, formatEventShortDate, formatHourMinute, formatPrice, safeUrl, sanitizeHtml, shareEvent, titleWithBrand, trackExternalClick, truncateForMeta, withLocaleQuery } from '../../utils';
import { useAuth } from '../../hooks/useAuth';
import { useEventReport } from '../../hooks/useEventReport';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useLogout } from '../../hooks/useLogout';
import { useOrganizerAuth } from '../../hooks/useOrganizerAuth';
import { useToast } from '../../hooks/useToast';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import { buildEventJsonLd } from '../../lib/structuredData';
import { type EventData } from '../../components/EventCard';
import EventOverflowMenu from '../../components/EventOverflowMenu';
import FeedbackButtonRow from '../../components/FeedbackButtonRow';
import PageState from '../../components/PageState';
import ReportModal from '../../components/ReportModal';
import SeoTags from '../../components/SeoTags';
import Toast from '../../components/Toast';
import TopBar from '../../components/TopBar';
import { useFeedback } from '../../hooks/useFeedback';
import { API, CLAIM_STATUS_PENDING, EVENT_CLAIM_STATUS_CLAIMED, EVENT_CLAIM_STATUS_NOT_CLAIMABLE, EVENT_PRICE_TESTID, EXPLORE_PARAM, OG_FALLBACK_IMAGE_PATH, PRICE_DATA_ATTR, PRODUCTION_ORIGIN, QUERY_KEYS, ROUTES, SEO_DESCRIPTION_MAX_LENGTH, UI_STATE, type ClaimStatus, type EventClaimStatus } from '../../constants';
import styles from './EventDetail.module.css';
import { ClaimPanel, ClaimPill } from '../../components/ClaimStrip';

interface EventDetailData extends EventData {
  language: string | null;
  claim_status: EventClaimStatus;
  listed_by: string | null;
}

export default function EventDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useLocaleNavigate();
  const localePath = useLocalePath();
  const authed = useAuth();
  const organizerAuthed = useOrganizerAuth();
  const { locale, handleLocaleChange, isPending: localePending } = useLocaleMutation({ publicRoute: true });
  const handleLogout = useLogout();
  const { toast, showToast } = useToast();

  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.event, id, locale],
    queryFn: () => api.get<EventDetailData>(withLocaleQuery(API.event(id ?? ''), locale)),
    enabled: Boolean(id),
    retry: false,
  });

  // (#451) GET /events/{id} never reveals a pending claim — the pending pill
  // is claimant-only, so an organizer-authed page asks this separate,
  // organizer-scoped endpoint for its *own* active claim on the event
  // instead of trusting anything public claim_status says about "pending".
  const { data: ownClaim } = useQuery({
    queryKey: [QUERY_KEYS.organizerClaimForEvent, data?.id],
    queryFn: () => organizerApi.get<{ claim: { status: ClaimStatus } | null }>(API.organizerClaimForEvent(data?.id ?? '')),
    enabled: Boolean(data?.id) && organizerAuthed,
  });

  const { reportOpen, reported, openReportModal, closeReportModal, handleReportSubmitted } = useEventReport(data?.reported ?? false, data?.id, authed, () => navigate(ROUTES.login));

  const { activeSignal, pending, sendFeedback } = useFeedback(data?.id, {
    initialSignal: data?.my_signal ?? null,
  });

  const sanitizedDescription = useMemo(
    () => (data?.description ? sanitizeHtml(data.description) : null),
    [data],
  );
  const sanitizedImportantInfo = useMemo(
    () => (data?.important_info ? sanitizeHtml(data.important_info) : null),
    [data],
  );

  // Only the loaded, real event opts into indexable OG/canonical/hreflang —
  // a still-loading or not-found page stays noindex rather than claiming a
  // canonical URL for content that isn't actually there (issue #48).
  const seoMeta = useSeoMeta({
    title: data
      ? titleWithBrand(`${data.title} – ${data.venue_name || formatEventShortDate(data.starts_at, locale)}`, locale)
      : titleWithBrand(t('event_not_found', locale), locale),
    locale,
    path: ROUTES.eventDetail(id ?? ''),
    indexable: Boolean(data),
    description: data && data.why_go.length > 0 ? truncateForMeta(data.why_go.join('. '), SEO_DESCRIPTION_MAX_LENGTH) : undefined,
    image: data ? (safeUrl(data.image_url) ?? `${PRODUCTION_ORIGIN}${OG_FALLBACK_IMAGE_PATH}`) : undefined,
  });
  const jsonLd = useMemo(() => (data ? buildEventJsonLd(data) : undefined), [data]);

  function handleTicketsClick() {
    if (!data || !authed) return;
    trackExternalClick(data.id);
  }

  async function handleShare() {
    const result = await shareEvent(data?.title, window.location.href);
    if (result === 'shared' || result === 'cancelled') return;
    showToast(result === 'copied' ? UI_STATE.success : UI_STATE.error, t(result === 'copied' ? 'link_copied' : 'share_failed', locale));
  }

  if (isLoading) {
    return (
      <>
        <SeoTags meta={seoMeta} />
        <PageState kind={UI_STATE.loading} message={t('loading_event', locale)} />
      </>
    );
  }

  if (isError || !data) {
    return (
      <>
        <SeoTags meta={seoMeta} />
        <PageState
          kind={UI_STATE.error}
          message={t('event_not_found', locale)}
          action={
            <button className={styles.backBtn} onClick={() => navigate(ROUTES.home)}>
              {t('back_to_feed_link', locale)}
            </button>
          }
        />
      </>
    );
  }

  const price = formatPrice(data.price_min, data.price_max, data.currency, locale, data.has_free_tier);
  const imageSrc = safeUrl(data.image_url);
  const ticketUrl = safeUrl(data.url);
  const mapsUrl = buildMapsUrl(data.lat, data.lng, data.venue_address);

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} jsonLd={jsonLd} />
      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
      <TopBar
        locale={locale}
        onLocaleChange={handleLocaleChange}
        onLogout={handleLogout}
        onBack={() => navigate(-1)}
        authed={authed}
        localeDisabled={localePending}
      />

      <main className={styles.main}>
        <div className={styles.hero}>
          {imageSrc ? (
            <div className={styles.heroFrame}>
              <img src={imageSrc} alt="" aria-hidden className={styles.heroBackdrop} loading="lazy" />
              <img src={imageSrc} alt={data.title} className={styles.heroImage} />
            </div>
          ) : (
            <div
              className={styles.heroPlaceholder}
              style={{ background: categoryGradient(data.categories) }}
              aria-hidden
            />
          )}
          {price && (
            // data-* attrs (PRICE_DATA_ATTR): read by the in-build SEO
            // validation gate (src/lib/seoValidation.ts, issue #53) to check
            // this snapshot's price against what the live API currently
            // returns — price isn't part of the JSON-LD payload (issue #46
            // defers AggregateOffer), so it needs its own marker.
            <span
              className={styles.price}
              data-testid={EVENT_PRICE_TESTID}
              {...{
                [PRICE_DATA_ATTR.min]: data.price_min ?? '',
                [PRICE_DATA_ATTR.max]: data.price_max ?? '',
                [PRICE_DATA_ATTR.currency]: data.currency ?? '',
                [PRICE_DATA_ATTR.hasFreeTier]: data.has_free_tier,
              }}
            >
              {price}
            </span>
          )}
        </div>

        <div className={styles.content}>
          {data.has_free_tier && (
            <p className={styles.freeTierHint}>{t('price_free_options_hint', locale)}</p>
          )}

          <div className={styles.meta}>
            <time className={styles.time}>{formatEventDateTime(data.starts_at, locale)}</time>
            {data.ends_at && (
              <span className={styles.ends}>
                {ti('ends_at', locale, { time: formatHourMinute(data.ends_at, locale) })}
              </span>
            )}
            {data.claim_status === EVENT_CLAIM_STATUS_CLAIMED && (
              <ClaimPill status="claimed" locale={locale} />
            )}
            {/* (#451) Claimant-only: the public claim_status never carries
                "pending" — only the caller's own claim, fetched via the
                organizer-scoped for-event lookup, can show this. */}
            {data.claim_status !== EVENT_CLAIM_STATUS_CLAIMED && ownClaim?.claim?.status === CLAIM_STATUS_PENDING && (
              <ClaimPill status="pending" locale={locale} />
            )}
          </div>

          <h1 className={styles.title}>{data.title}</h1>

          {data.listed_by && (
            <p className={styles.listedBy}>{ti('listed_by', locale, { name: data.listed_by })}</p>
          )}

          <div className={styles.actions}>
            {authed && (
              <FeedbackButtonRow
                activeSignal={activeSignal}
                pending={pending}
                onPress={sendFeedback}
                locale={locale}
                variant="detail"
              />
            )}
            <EventOverflowMenu
              locale={locale}
              reported={reported}
              onShare={handleShare}
              onReport={openReportModal}
              triggerClassName={styles.overflowTrigger}
            />
            {ticketUrl && (
              <a
                href={ticketUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.ticketsBtn}
                onClick={handleTicketsClick}
              >
                {t('get_tickets', locale)}
              </a>
            )}
          </div>

          {data.why_go.length > 0 && (
            <section className={styles.section}>
              <h2 className={styles.eyebrow}>{t('why_go', locale)}</h2>
              <hr className={styles.rule} />
              <ul className={styles.bullets}>
                {data.why_go.map(bullet => (
                  <li key={bullet} className={styles.bullet}>{bullet}</li>
                ))}
              </ul>
            </section>
          )}

          {sanitizedDescription && (
            <section className={styles.section}>
              <h2 className={styles.eyebrow}>{t('eyebrow_about', locale)}</h2>
              <hr className={styles.rule} />
              <div className={styles.description} dangerouslySetInnerHTML={{ __html: sanitizedDescription }} />
            </section>
          )}

          {sanitizedImportantInfo && (
            <section className={styles.section}>
              <h2 className={styles.eyebrow}>{t('eyebrow_important_info', locale)}</h2>
              <hr className={styles.rule} />
              <div className={styles.description} dangerouslySetInnerHTML={{ __html: sanitizedImportantInfo }} />
            </section>
          )}

          {(data.venue_name || data.venue_address || data.categories.length > 0 || data.vibes.length > 0) && (
            <section className={styles.section}>
              <h2 className={styles.eyebrow}>{t('eyebrow_details', locale)}</h2>
              <hr className={styles.rule} />
              {(data.venue_name || data.venue_address) && (
                <div className={styles.venue}>
                  {data.venue_name && <span className={styles.venueName}>{data.venue_name}</span>}
                  {data.venue_address && (
                    <span className={styles.venueAddress}>{data.venue_address}</span>
                  )}
                  {mapsUrl && (
                    <a href={mapsUrl} target="_blank" rel="noopener noreferrer" className={styles.mapLink}>
                      {t('view_on_map', locale)}
                    </a>
                  )}
                </div>
              )}

              {(data.categories.length > 0 || data.vibes.length > 0) && (
                <div className={styles.tags}>
                  {data.categories.map(cat => (
                    <Link key={cat} to={localePath(`${ROUTES.explore}?${EXPLORE_PARAM.category}=${cat}`)} className={styles.tag}>
                      {t(`category_${cat}`, locale)}
                    </Link>
                  ))}
                  {data.vibes.map(vibe => (
                    <Link key={vibe} to={localePath(`${ROUTES.explore}?${EXPLORE_PARAM.vibe}=${vibe}`)} className={cx(styles.tag, styles.tagVibe)}>
                      {t(`vibe_${vibe}`, locale)}
                    </Link>
                  ))}
                </div>
              )}
            </section>
          )}

          {/* #441: a pending-only target is still claimable by a rival —
              ADR 0004's "proof preempts assertion" only blocks the CTA once
              a claim is actually approved. #445: a direct organizer
              submission has no ingested EventSource to ever claim, so the
              CTA never renders for it. */}
          {data.claim_status !== EVENT_CLAIM_STATUS_CLAIMED &&
            data.claim_status !== EVENT_CLAIM_STATUS_NOT_CLAIMABLE && (
              <ClaimPanel eventId={data.id} locale={locale} />
            )}
        </div>
      </main>

      {reportOpen && (
        <ReportModal
          open={reportOpen}
          onClose={closeReportModal}
          eventId={data.id}
          locale={locale}
          onSubmitted={handleReportSubmitted}
        />
      )}
    </div>
  );
}
