import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { setLocale } from '../lib/auth';
import { LOCALES, PERSONAS } from '../constants';
import { t, ti, personaName, personaVibe } from '../i18n';
import LocaleSelector from '../components/LocaleSelector';
import PersonaCard from '../components/PersonaCard';
import styles from './Onboarding.module.css';

export default function Onboarding() {
  const navigate = useNavigate();
  const [primarySlug, setPrimarySlug] = useState<string | null>(null);
  const [secondarySlug, setSecondarySlug] = useState<string | null>(null);
  const [locale, setLocaleState] = useState<string>(LOCALES[0].code);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  function handleClickPrimary(slug: string) {
    if (primarySlug === slug) {
      setPrimarySlug(null);
      if (secondarySlug === slug) setSecondarySlug(null);
    } else {
      setPrimarySlug(slug);
      if (secondarySlug === slug) setSecondarySlug(null);
    }
  }

  function handleClickSecondary(slug: string) {
    if (secondarySlug === slug) {
      setSecondarySlug(null);
    } else {
      setSecondarySlug(slug);
    }
  }

  function roleFor(slug: string): 'none' | 'primary' | 'secondary' {
    if (slug === primarySlug) return 'primary';
    if (slug === secondarySlug) return 'secondary';
    return 'none';
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!primarySlug) return;
    setLoading(true);
    setError('');
    try {
      await api.post('/onboarding/persona', {
        primary_slug: primarySlug,
        ...(secondarySlug ? { secondary_slug: secondarySlug } : {}),
      });
      setLocale(locale);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('generic_error', locale));
      setLoading(false);
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <span className={styles.radar} aria-hidden>◉</span>
        <span className={styles.brand}>Event Radar</span>

        <LocaleSelector locale={locale} onChange={setLocaleState} ariaLabel="Language" />
      </header>

      <main className={styles.main}>
        <div className={styles.intro}>
          <h1 className={styles.heading}>{t('onboarding_heading', locale)}</h1>
          <p className={styles.sub}>{t('onboarding_sub', locale)}</p>
        </div>

        <form onSubmit={handleSubmit}>
          <div className={styles.grid}>
            {PERSONAS.map((p) => (
              <PersonaCard
                key={p.slug}
                persona={{ ...p, name: personaName(p.slug, locale), vibe: personaVibe(p.slug, locale) }}
                role={roleFor(p.slug)}
                primaryTaken={!!primarySlug && primarySlug !== p.slug}
                locale={locale}
                onClickPrimary={() => handleClickPrimary(p.slug)}
                onClickSecondary={() => handleClickSecondary(p.slug)}
              />
            ))}
          </div>

          {error && (
            <p className={styles.error} role="alert">{error}</p>
          )}

          <div className={styles.cta}>
            {secondarySlug && (
              <p className={styles.blend}>
                {ti('persona_blending', locale, {
                  primary: personaName(primarySlug ?? '', locale),
                  secondary: personaName(secondarySlug, locale),
                })}
              </p>
            )}
            <button
              type="submit"
              className={styles.submit}
              disabled={!primarySlug || loading}
            >
              {loading
                ? <span className={styles.spinner} aria-label={t('saving', locale)} />
                : t('lets_go', locale)}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
