import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '../api/client';
import { getLocale, setLocale } from '../lib/auth';
import { LOCALES, PERSONAS, SAVE_MSG_CLEAR_DELAY_MS, PERSONA_PRIMARY_WEIGHT_THRESHOLD } from '../constants';
import { t, personaName } from '../i18n';
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
      setSaveMsg(t('saved', locale));
      setSaveError('');
      setTimeout(() => setSaveMsg(''), SAVE_MSG_CLEAR_DELAY_MS);
    },
    onError: (err, variables) => {
      setSaveError(err instanceof ApiError ? err.message : t('save_failed', locale));
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

  const primaryPersona = data?.personas.find((p) => p.weight >= PERSONA_PRIMARY_WEIGHT_THRESHOLD);
  const secondaryPersona = data?.personas.find((p) => p.weight < PERSONA_PRIMARY_WEIGHT_THRESHOLD);

  function personaEmoji(slug: string): string {
    return PERSONAS.find((p) => p.slug === slug)?.emoji ?? '◉';
  }

  if (isLoading) {
    return (
      <div className={styles.centered}>
        <span className={styles.spinner} aria-label={t('loading', locale)} />
      </div>
    );
  }

  if (isError) {
    return (
      <div className={styles.centered}>
        <p className={styles.errorMsg}>{t('settings_error', locale)}</p>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.topBar}>
        <Link to="/" className={styles.back} aria-label={t('back_to_feed', locale)}>{t('back_to_feed', locale)}</Link>
        <div className={styles.logoWrap}>
          <span className={styles.radar} aria-hidden>◉</span>
          <span className={styles.brand}>{t('settings_link', locale)}</span>
        </div>
        <div className={styles.topBarSpacer} aria-hidden />
      </header>

      <main className={styles.main}>
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_account', locale)}</h2>
          <p className={styles.email}>{data?.email}</p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_language', locale)}</h2>
          <div className={styles.localePills} role="group" aria-label={t('section_language', locale)}>
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
          <h2 className={styles.sectionTitle}>{t('section_persona', locale)}</h2>
          <div className={styles.personaDisplay}>
            {primaryPersona ? (
              <div className={styles.personaRow}>
                <span className={styles.personaEmoji}>{personaEmoji(primaryPersona.slug)}</span>
                <div>
                  <span className={styles.personaName}>
                    {personaName(primaryPersona.slug, locale)}
                  </span>
                  <span className={styles.personaBadge}>{t('persona_primary', locale)}</span>
                </div>
              </div>
            ) : (
              <p className={styles.noPersona}>{t('no_persona', locale)}</p>
            )}
            {secondaryPersona && (
              <div className={styles.personaRow}>
                <span className={styles.personaEmoji}>{personaEmoji(secondaryPersona.slug)}</span>
                <div>
                  <span className={styles.personaName}>
                    {personaName(secondaryPersona.slug, locale)}
                  </span>
                  <span className={[styles.personaBadge, styles.secondaryBadge].join(' ')}>{t('persona_secondary', locale)}</span>
                </div>
              </div>
            )}
          </div>
          <button
            className={styles.repickBtn}
            onClick={() => navigate('/onboarding')}
          >
            {t('change_persona', locale)}
          </button>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_digest', locale)}</h2>
          <div className={styles.toggleRow}>
            <div>
              <p className={styles.toggleLabel}>{t('digest_label', locale)}</p>
              <p className={styles.toggleDesc}>{t('digest_desc', locale)}</p>
            </div>
            <button
              className={[styles.toggle, data?.email_digest_opt_in ? styles.toggleOn : styles.toggleOff].join(' ')}
              onClick={handleOptInToggle}
              disabled={patchMutation.isPending}
              aria-pressed={data?.email_digest_opt_in}
              aria-label={data?.email_digest_opt_in ? t('digest_unsubscribe', locale) : t('digest_subscribe', locale)}
            >
              <span className={styles.toggleKnob} />
            </button>
          </div>
          {!data?.email_digest_opt_in && (
            <p className={styles.unsubMsg}>{t('digest_off', locale)}</p>
          )}
        </section>

        {saveMsg && <p className={styles.saveSuccess} role="status">{saveMsg}</p>}
        {saveError && <p className={styles.saveError} role="alert">{saveError}</p>}
      </main>
    </div>
  );
}
