import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { t, ti } from '../../i18n';
import { buildMapsUrl, categoryGradient, cx, formatEventDateTime, formatHourMinute, formatPrice, safeUrl, sanitizeHtml, trackExternalClick } from '../../utils';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { type EventData } from '../../components/EventCard';
import FeedbackButtonRow from '../../components/FeedbackButtonRow';
import LocaleSelector from '../../components/LocaleSelector';
import PageState from '../../components/PageState';
import { useFeedback } from '../../hooks/useFeedback';
import { QUERY_KEYS } from '../../constants';
import styles from './EventDetail.module.css';

interface EventDetailData extends EventData {
  language: string | null;
}

export default function EventDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { locale, handleLocaleChange } = useLocaleMutation([QUERY_KEYS.event, id]);

  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.event, id],
    queryFn: () => api.get<EventDetailData>(`/events/${id}`),
    enabled: Boolean(id),
    retry: false,
  });

  const { activeSignal, pending, sendFeedback } = useFeedback(data?.id ?? 0, {
    initialSignal: data?.my_signal ?? null,
  });

  function handleTicketsClick() {
    if (!data) return;
    trackExternalClick(data.id);
  }

  if (isLoading) {
    return <PageState kind="loading" message={t('loading_event', locale)} />;
  }

  if (isError || !data) {
    return (
      <PageState
        kind="error"
        message={t('event_not_found', locale)}
        action={
          <button className={styles.backBtn} onClick={() => navigate('/')}>
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
      <header className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => navigate(-1)} aria-label={t('back', locale)}>
          {t('back', locale)}
        </button>
        <Link to="/" className={styles.logoWrap}>
          <span className={styles.radar} aria-hidden>◉</span>
          <span className={styles.brand}>{t('brand', locale)}</span>
        </Link>
        <LocaleSelector locale={locale} onChange={handleLocaleChange} ariaLabel={t('section_language', locale)} />
      </header>

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

          {data.description && (
            <section className={styles.section}>
              <h2 className={styles.eyebrow}>{t('eyebrow_about', locale)}</h2>
              <hr className={styles.rule} />
              <div className={styles.description} dangerouslySetInnerHTML={{ __html: sanitizeHtml(data.description) }} />
            </section>
          )}

          {data.important_info && (
            <section className={styles.section}>
              <h2 className={styles.eyebrow}>{t('eyebrow_important_info', locale)}</h2>
              <hr className={styles.rule} />
              <div className={styles.description} dangerouslySetInnerHTML={{ __html: sanitizeHtml(data.important_info) }} />
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
                    <span key={cat} className={styles.tag}>{t(`category_${cat}`, locale)}</span>
                  ))}
                  {data.vibes.map(vibe => (
                    <span key={vibe} className={cx(styles.tag, styles.tagVibe)}>{t(`vibe_${vibe}`, locale)}</span>
                  ))}
                </div>
              )}
            </section>
          )}

          <div className={styles.actions}>
            <FeedbackButtonRow
              activeSignal={activeSignal}
              pending={pending}
              onPress={sendFeedback}
              locale={locale}
              variant="detail"
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
        </div>
      </main>
    </div>
  );
}
