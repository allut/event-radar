import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError } from '../../api/client';
import { getLocale, setLocale } from '../../lib/auth';
import { useLogout } from '../../hooks/useLogout';
import { API, PERSONAS, PERSONA_MAX_SELECTABLE, ROUTES } from '../../constants';
import { t, ti, personaName, personaVibe } from '../../i18n';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import PersonaCard from '../../components/PersonaCard';
import TopBar from '../../components/TopBar';
import SeoTags from '../../components/SeoTags';
import styles from './Onboarding.module.css';

export default function Onboarding() {
  const navigate = useNavigate();
  const handleLogout = useLogout();
  const [selected, setSelected] = useState<string[]>([]);
  const [locale, setLocaleState] = useState<string>(getLocale());
  const seoMeta = useStaticSeoMeta('onboarding_heading', locale);

  function handleLocaleChange(code: string) {
    setLocaleState(code);
    setLocale(code);
  }
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  function toggle(slug: string) {
    setSelected((prev) => {
      if (prev.includes(slug)) return prev.filter((s) => s !== slug);
      if (prev.length >= PERSONA_MAX_SELECTABLE) return prev;
      return [...prev, slug];
    });
  }

  function rankFor(slug: string): number {
    return selected.indexOf(slug) + 1;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (selected.length < 1) return;
    setIsLoading(true);
    setError('');
    try {
      await api.post(API.onboardingPersona, { persona_slugs: selected });
      setLocale(locale);
      navigate(ROUTES.home, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('generic_error', locale));
      setIsLoading(false);
    }
  }

  const atCap = selected.length >= PERSONA_MAX_SELECTABLE;

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <TopBar
        locale={locale}
        onLocaleChange={handleLocaleChange}
        onLogout={handleLogout}
        onBack={() => navigate(ROUTES.settings)}
        showNav={false}
      />

      <main className={styles.main}>
        <div className={styles.intro}>
          <h1 className={styles.heading}>{t('onboarding_heading', locale)}</h1>
          <p className={styles.sub}>{t('onboarding_sub', locale)}</p>
          <p className={styles.meter}>
            {atCap
              ? ti('persona_count_full', locale, { max: String(PERSONA_MAX_SELECTABLE) })
              : ti('persona_count', locale, {
                  count: String(selected.length),
                  max: String(PERSONA_MAX_SELECTABLE),
                })}
          </p>
        </div>

        <form onSubmit={handleSubmit}>
          <div className={styles.grid}>
            {PERSONAS.map((p) => {
              const rank = rankFor(p.slug);
              return (
                <PersonaCard
                  key={p.slug}
                  persona={{ ...p, name: personaName(p.slug, locale), vibe: personaVibe(p.slug, locale) }}
                  rank={rank}
                  disabled={atCap && rank === 0}
                  locale={locale}
                  onToggle={() => toggle(p.slug)}
                />
              );
            })}
          </div>

          {error && (
            <p className={styles.error} role="alert">{error}</p>
          )}

          <div className={styles.cta}>
            <button
              type="submit"
              className={styles.submit}
              disabled={selected.length < 1 || isLoading}
            >
              {isLoading
                ? <span className={styles.spinner} aria-label={t('saving', locale)} />
                : t('lets_go', locale)}
            </button>
          </div>
        </form>
      </main>

      {isLoading && (
        <div className={styles.overlay} role="status" aria-live="polite">
          <div className={styles.overlayPanel}>
            <span className={styles.overlaySpinner} />
            <p className={styles.overlayMsg}>{t('onboarding_saving_msg', locale)}</p>
          </div>
        </div>
      )}
    </div>
  );
}
