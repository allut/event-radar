import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { setLocale } from '../../lib/auth';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { useLogout } from '../../hooks/useLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { PERSONA_MAX_SELECTABLE } from '../../_generated/sharedConstants';
import { API, QUERY_KEYS } from '../../constants/api';
import { PERSONAS } from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import { t, ti, personaName, personaVibe } from '../../i18n';
import { apiErrorMessage } from '../../utils/apiErrors';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import PersonaCard from '../../components/PersonaCard';
import TopBar from '../../components/TopBar';
import SeoTags from '../../components/SeoTags';
import styles from './Onboarding.module.css';

export default function Onboarding() {
  const navigate = useLocaleNavigate();
  const handleLogout = useLogout();
  const [selected, setSelected] = useState<string[]>([]);
  const [locale, handleLocaleChange] = useLocalLocale();
  const seoMeta = useStaticSeoMeta('onboarding_heading', locale);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  // null until the user touches the box; until then it mirrors the saved choice
  // (false for a new user, the current value for someone re-picking personas).
  const [digestChoice, setDigestChoice] = useState<boolean | null>(null);
  const queryClient = useQueryClient();
  const { data: settings, isPending: settingsPending } = useQuery({
    queryKey: [QUERY_KEYS.settings],
    queryFn: () => api.get<{ email_digest_opt_in: boolean }>(API.me),
  });
  const savedDigest = digestChoice ?? settings?.email_digest_opt_in;
  const digestOn = savedDigest ?? false;

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
      // Omitted while the saved value is unknown, so a failed read never unsubscribes.
      await api.post(API.onboardingPersona, {
        persona_slugs: selected,
        ...(savedDigest !== undefined && { email_digest_opt_in: savedDigest }),
      });
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.settings] });
      setLocale(locale);
      navigate(ROUTES.home, { replace: true });
    } catch (err) {
      setError(apiErrorMessage(err, t('generic_error', locale)));
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

          <div className={styles.digest}>
            <label className={styles.digestRow} htmlFor="digest-opt-in">
              <input
                id="digest-opt-in"
                type="checkbox"
                className={styles.digestInput}
                checked={digestOn}
                disabled={settingsPending}
                onChange={(e) => setDigestChoice(e.target.checked)}
              />
              <span className={styles.digestBox}>
                <svg className={styles.digestMark} viewBox="0 0 14 14" aria-hidden="true">
                  <path d="M2 7.5l3.5 3.5L12 3.5" />
                </svg>
              </span>
              <span>
                <span className={styles.digestTitle}>{t('onboarding_digest_label', locale)}</span>
                <span className={styles.digestDesc}>{t('onboarding_digest_desc', locale)}</span>
              </span>
            </label>
            <p className={styles.digestState} aria-live="polite">
              {t(digestOn ? 'onboarding_digest_on' : 'onboarding_digest_off', locale)}
            </p>
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
