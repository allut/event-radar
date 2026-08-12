import { useMemo } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { t, ti } from '../../i18n';
import { buildMapsUrl, categoryGradient, copyToClipboard, cx, formatEventDateTime, formatHourMinute, formatPrice, safeUrl, sanitizeHtml, trackExternalClick } from '../../utils';
import { useAuth } from '../../hooks/useAuth';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLogout } from '../../hooks/useLogout';
import { useToast } from '../../hooks/useToast';
import { type EventData } from '../../components/EventCard';
import FeedbackButtonRow from '../../components/FeedbackButtonRow';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import TopBar from '../../components/TopBar';
import { useFeedback } from '../../hooks/useFeedback';
import { API, QUERY_KEYS, ROUTES, UI_STATE } from '../../constants';
import styles from './EventDetail.module.css';

interface EventDetailData extends EventData {
  language: string | null;
}

const ShareIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
    <path d="M12 15V3" />
    <path d="M8 7l4-4 4 4" />
    <path d="M4 13v6a2 2 0 002 2h12a2 2 0 002-2v-6" />
  </svg>
);

export default function EventDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const authed = useAuth();
  const { locale, handleLocaleChange } = useLocaleMutation();
  const handleLogout = useLogout();
  const { toast, showToast } = useToast();

  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.event, id, locale],
    queryFn: () => api.get<EventDetailData>(`${API.event(id ?? '')}?locale=${encodeURIComponent(locale)}`),
    enabled: Boolean(id),
    retry: false,
  });

  const { activeSignal, pending, sendFeedback } = useFeedback(data?.id ?? 0, {
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

  function handleTicketsClick() {
    if (!data || !authed) return;
    trackExternalClick(data.id);
  }

  async function handleShare() {
    const url = window.location.href;
    if (navigator.share) {
      try {
        await navigator.share({ title: data?.title, url });
        return;
      } catch (err) {
        // user cancelled — respect that, don't fall through to copy
        if (err instanceof DOMException && err.name === 'AbortError') return;
        // unsupported/blocked share — fall through to copy
      }
    }
    const ok = await copyToClipboard(url);
    showToast(ok ? UI_STATE.success : UI_STATE.error, t(ok ? 'link_copied' : 'share_failed', locale));
  }

  if (isLoading) {
    return <PageState kind={UI_STATE.loading} message={t('loading_event', locale)} />;
  }

  if (isError || !data) {
    return (
      <PageState
        kind={UI_STATE.error}
        message={t('event_not_found', locale)}
        action={
          <button className={styles.backBtn} onClick={() => navigate(ROUTES.home)}>
            {t('back_to_feed_link', locale)}
          </button>
        }
      />
    );
  }

  const price = formatPrice(data.price_min, data.price_max, data.currency, locale, data.has_free_tier);
  const imageSrc = safeUrl(data.image_url);
  const ticketUrl = safeUrl(data.url);
  const mapsUrl = buildMapsUrl(data.lat, data.lng, data.venue_address);

  return (
    <div className={styles.page}>
      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
      <TopBar
        locale={locale}
        onLocaleChange={handleLocaleChange}
        onLogout={handleLogout}
        onBack={() => navigate(-1)}
        authed={authed}
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
          {price && <span className={styles.price}>{price}</span>}
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
          </div>

          <h1 className={styles.title}>{data.title}</h1>

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
            <button className={styles.shareBtn} onClick={handleShare} aria-label={t('share', locale)}>
              <ShareIcon />
              <span className={styles.shareLabel}>{t('share', locale)}</span>
            </button>
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
                    <Link key={cat} to={`/explore?category=${cat}`} className={styles.tag}>
                      {t(`category_${cat}`, locale)}
                    </Link>
                  ))}
                  {data.vibes.map(vibe => (
                    <Link key={vibe} to={`/explore?vibe=${vibe}`} className={cx(styles.tag, styles.tagVibe)}>
                      {t(`vibe_${vibe}`, locale)}
                    </Link>
                  ))}
                </div>
              )}
            </section>
          )}

        </div>
      </main>
    </div>
  );
}
