import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { API, BRAND_GLYPH, MAGIC_LINK_EXPIRY_MINUTES, OG_FALLBACK_IMAGE_PATH, PERSONAS, PRODUCTION_ORIGIN, QUERY_KEYS, ROUTES, STEP_KEYS, UI_STATE } from '../../constants';
import { t, ti, personaName, personaVibe } from '../../i18n';
import { padIndex, withLocaleQuery } from '../../utils';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLocalePath } from '../../hooks/useLocalePath';
import { useMagicLinkRequest } from '../../hooks/useMagicLinkRequest';
import { useOrganizerAuth } from '../../hooks/useOrganizerAuth';
import { useSeoMeta } from '../../hooks/useSeoMeta';
import { buildWebsiteJsonLd } from '../../lib/structuredData';
import TopBar from '../../components/TopBar';
import EventCard, { type EventData } from '../../components/EventCard';
import SeoTags from '../../components/SeoTags';
import RadarHero from './RadarHero';
import styles from './Landing.module.css';

interface ShowcaseResponse {
  events: EventData[];
}

function EmailCapture({ locale }: { locale: string }) {
  const { email, setEmail, state, errorMsg, submit } = useMagicLinkRequest(locale);

  if (state === UI_STATE.success) {
    return (
      <div className={styles.success} role="status">
        <div className={styles.checkCircle}>✓</div>
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
  const jsonLd = buildWebsiteJsonLd(locale);

  const { data, isError } = useQuery({
    queryKey: [QUERY_KEYS.showcase, locale],
    queryFn: () => api.get<ShowcaseResponse>(withLocaleQuery(API.publicShowcase, locale)),
    retry: false,
  });

  const showcaseEvents = data?.events ?? [];

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} jsonLd={jsonLd} />
      <TopBar locale={locale} onLocaleChange={handleLocaleChange} authed={false} localeDisabled={localePending} />

      <main>
        <section className={styles.hero}>
          <div className={styles.heroText}>
            <h1 className={styles.h1}>{t('landing_hero_h1', locale)}</h1>
            <p className={styles.sub}>{t('landing_hero_sub', locale)}</p>
            <EmailCapture locale={locale} />
            <a href="#showcase" className={styles.secondaryCta}>{t('landing_cta_explore', locale)}</a>
          </div>
          <div className={styles.heroArt}>
            <RadarHero locale={locale} />
          </div>
        </section>

        <section className={styles.steps} aria-label={t('landing_how_title', locale)}>
          <h2 className={styles.sectionTitle}>{t('landing_how_title', locale)}</h2>
          <ol className={styles.stepList}>
            {STEP_KEYS.map((step, i) => (
              <li key={step.title} className={styles.step}>
                <span className={styles.stepNum} aria-hidden>{padIndex(i + 1)}</span>
                <h3 className={styles.stepTitle}>{t(step.title, locale)}</h3>
                <p className={styles.stepBody}>{t(step.body, locale)}</p>
              </li>
            ))}
          </ol>
        </section>

        {(showcaseEvents.length > 0 || isError) && (
          <section id="showcase" className={styles.showcase}>
            <h2 className={styles.sectionTitle}>{t('landing_showcase_title', locale)}</h2>
            <p className={styles.sectionSub}>{t('landing_showcase_sub', locale)}</p>
            {isError ? (
              <p className={styles.error} role="alert">{t('landing_showcase_error', locale)}</p>
            ) : (
              <>
                <div className={styles.grid}>
                  {showcaseEvents.map((event, i) => (
                    <EventCard key={event.id} event={event} index={i} locale={locale} readOnly />
                  ))}
                </div>
                <Link to={localePath(ROUTES.login)} className={styles.showcaseCta}>{t('landing_showcase_cta', locale)}</Link>
              </>
            )}
          </section>
        )}

        <section className={styles.personas}>
          <h2 className={styles.sectionTitle}>{t('landing_personas_title', locale)}</h2>
          <p className={styles.sectionSub}>{t('landing_personas_sub', locale)}</p>
          <div className={styles.personaRow}>
            {PERSONAS.map((persona) => (
              <div key={persona.slug} className={styles.personaChip}>
                <span className={styles.personaEmoji} aria-hidden>{persona.emoji}</span>
                <span className={styles.personaName}>{personaName(persona.slug, locale)}</span>
                <span className={styles.personaVibe}>{personaVibe(persona.slug, locale)}</span>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.organizer} aria-labelledby="organizer-cta">
          <div className={styles.organizerText}>
            <p className={styles.organizerEyebrow}>
              <span className={styles.organizerMark} aria-hidden>{BRAND_GLYPH}</span>
              {t('landing_organizer_eyebrow', locale)}
            </p>
            <h2 id="organizer-cta" className={styles.organizerTitle}>{t('landing_organizer_title', locale)}</h2>
            <p className={styles.organizerBody}>{t('landing_organizer_body', locale)}</p>
          </div>
          <Link to={localePath(isOrganizer ? ROUTES.organizerDashboard : ROUTES.organizerLogin)} className={styles.organizerCta}>
            {t('landing_organizer_cta', locale)}
          </Link>
        </section>

        <section className={styles.trust}>
          <span className={styles.trustItem}>{t('landing_trust_nopassword', locale)}</span>
          <span className={styles.trustDot} aria-hidden>·</span>
          <span className={styles.trustItem}>{t('landing_trust_notracking', locale)}</span>
          <span className={styles.trustDot} aria-hidden>·</span>
          <span className={styles.trustItem}>{t('landing_trust_free', locale)}</span>
        </section>
      </main>
    </div>
  );
}
