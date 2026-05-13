import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { setLocale } from '../lib/auth';
import { LOCALES, PERSONAS } from '../constants';
import PersonaCard from '../components/PersonaCard';
import styles from './Onboarding.module.css';

export default function Onboarding() {
  const navigate = useNavigate();
  const [primarySlug, setPrimarySlug] = useState<string | null>(null);
  const [secondarySlug, setSecondarySlug] = useState<string | null>(null);
  const [locale, setLocaleState] = useState('en');
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
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.');
      setLoading(false);
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <span className={styles.radar} aria-hidden>◉</span>
        <span className={styles.brand}>Event Radar</span>

        <div className={styles.localePills} role="group" aria-label="Language">
          {LOCALES.map(({ code, label }) => (
            <button
              key={code}
              type="button"
              className={[styles.localePill, locale === code ? styles.activeLocale : ''].join(' ')}
              onClick={() => setLocaleState(code)}
              aria-pressed={locale === code}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <main className={styles.main}>
        <div className={styles.intro}>
          <h1 className={styles.heading}>What's your vibe?</h1>
          <p className={styles.sub}>
            Pick one primary persona. Optionally add a secondary to widen your feed.
          </p>
        </div>

        <form onSubmit={handleSubmit}>
          <div className={styles.grid}>
            {PERSONAS.map((p) => (
              <PersonaCard
                key={p.slug}
                persona={p}
                role={roleFor(p.slug)}
                primaryTaken={!!primarySlug && primarySlug !== p.slug}
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
                Blending <strong>{PERSONAS.find(p => p.slug === primarySlug)?.name}</strong> with{' '}
                <strong>{PERSONAS.find(p => p.slug === secondarySlug)?.name}</strong>
              </p>
            )}
            <button
              type="submit"
              className={styles.submit}
              disabled={!primarySlug || loading}
            >
              {loading
                ? <span className={styles.spinner} aria-label="Saving…" />
                : "Let's go →"}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
