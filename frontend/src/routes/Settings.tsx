import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '../api/client';
import { getLocale, setLocale } from '../lib/auth';
import { LOCALES, PERSONAS } from '../constants';
import styles from './Settings.module.css';

interface PersonaEntry {
  slug: string;
  display_name_en: string;
  weight: number;
}

interface SettingsData {
  id: number;
  email: string;
  locale: string;
  home_city: string;
  email_digest_opt_in: boolean;
  created_at: string;
  personas: PersonaEntry[];
}

export default function Settings() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get<SettingsData>('/users/me'),
  });

  const [locale, setLocaleState] = useState(getLocale());
  const [saveMsg, setSaveMsg] = useState('');
  const [saveError, setSaveError] = useState('');

  const patchMutation = useMutation({
    mutationFn: (body: Partial<{ locale: string; email_digest_opt_in: boolean }>) =>
      api.patch<SettingsData>('/users/me', body),
    onSuccess: (updated) => {
      queryClient.setQueryData(['settings'], updated);
      setSaveMsg('Saved.');
      setSaveError('');
      setTimeout(() => setSaveMsg(''), 2000);
    },
    onError: (err, variables) => {
      setSaveError(err instanceof ApiError ? err.message : 'Save failed.');
      if (variables.locale !== undefined) {
        setLocaleState(getLocale());
      }
    },
  });

  function handleLocaleChange(code: string) {
    setLocaleState(code);
    patchMutation.mutate(
      { locale: code },
      { onSuccess: () => setLocale(code) },
    );
  }

  function handleOptInToggle() {
    if (!data) return;
    patchMutation.mutate({ email_digest_opt_in: !data.email_digest_opt_in });
  }

  const primaryPersona = data?.personas.find((p) => p.weight >= 0.9);
  const secondaryPersona = data?.personas.find((p) => p.weight < 0.9);

  function personaEmoji(slug: string): string {
    return PERSONAS.find((p) => p.slug === slug)?.emoji ?? '◉';
  }

  if (isLoading) {
    return (
      <div className={styles.centered}>
        <span className={styles.spinner} aria-label="Loading…" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className={styles.centered}>
        <p className={styles.errorMsg}>Failed to load settings. Please refresh.</p>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <Link to="/" className={styles.back} aria-label="Back to feed">← Feed</Link>
        <div className={styles.logoWrap}>
          <span className={styles.radar} aria-hidden>◉</span>
          <span className={styles.brand}>Settings</span>
        </div>
        <div className={styles.topBarSpacer} aria-hidden />
      </header>

      <main className={styles.main}>
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Account</h2>
          <p className={styles.email}>{data?.email}</p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Language</h2>
          <div className={styles.localePills} role="group" aria-label="Language">
            {LOCALES.map(({ code, label }) => (
              <button
                key={code}
                className={[styles.localePill, locale === code ? styles.activeLocale : ''].join(' ')}
                onClick={() => handleLocaleChange(code)}
                aria-pressed={locale === code}
                disabled={patchMutation.isPending}
              >
                {label}
              </button>
            ))}
          </div>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Persona</h2>
          <div className={styles.personaDisplay}>
            {primaryPersona ? (
              <div className={styles.personaRow}>
                <span className={styles.personaEmoji}>{personaEmoji(primaryPersona.slug)}</span>
                <div>
                  <span className={styles.personaName}>
                    {PERSONAS.find((p) => p.slug === primaryPersona.slug)?.name ?? primaryPersona.display_name_en}
                  </span>
                  <span className={styles.personaBadge}>Primary</span>
                </div>
              </div>
            ) : (
              <p className={styles.noPersona}>No persona selected.</p>
            )}
            {secondaryPersona && (
              <div className={styles.personaRow}>
                <span className={styles.personaEmoji}>{personaEmoji(secondaryPersona.slug)}</span>
                <div>
                  <span className={styles.personaName}>
                    {PERSONAS.find((p) => p.slug === secondaryPersona.slug)?.name ?? secondaryPersona.display_name_en}
                  </span>
                  <span className={[styles.personaBadge, styles.secondaryBadge].join(' ')}>Secondary</span>
                </div>
              </div>
            )}
          </div>
          <button
            className={styles.repickBtn}
            onClick={() => navigate('/onboarding')}
          >
            Change persona →
          </button>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Email digest</h2>
          <div className={styles.toggleRow}>
            <div>
              <p className={styles.toggleLabel}>Daily Five digest</p>
              <p className={styles.toggleDesc}>Receive your Daily Five by email each morning.</p>
            </div>
            <button
              className={[styles.toggle, data?.email_digest_opt_in ? styles.toggleOn : styles.toggleOff].join(' ')}
              onClick={handleOptInToggle}
              disabled={patchMutation.isPending}
              aria-pressed={data?.email_digest_opt_in}
              aria-label={data?.email_digest_opt_in ? 'Unsubscribe from email digest' : 'Subscribe to email digest'}
            >
              <span className={styles.toggleKnob} />
            </button>
          </div>
          {!data?.email_digest_opt_in && (
            <p className={styles.unsubMsg}>
              Email digest is off. You can re-enable it any time.
            </p>
          )}
        </section>

        {saveMsg && <p className={styles.saveSuccess} role="status">{saveMsg}</p>}
        {saveError && <p className={styles.saveError} role="alert">{saveError}</p>}
      </main>
    </div>
  );
}
