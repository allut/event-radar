import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '../../api/client';
import { getLocale } from '../../lib/auth';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLogout } from '../../hooks/useLogout';
import { useToast } from '../../hooks/useToast';
import { AUTH_REDIRECT_DELAY_MS, PERSONAS, QUERY_KEYS, UI_STATE, TOAST_IDLE, type ToastState } from '../../constants';
import { cx } from '../../utils';
import { t, personaName } from '../../i18n';
import LocaleSelector from '../../components/LocaleSelector';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import Toggle from '../../components/Toggle';
import TopBar from '../../components/TopBar';
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
  const handleLogout = useLogout();

  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.settings],
    queryFn: () => api.get<SettingsData>('/users/me'),
  });

  const { toast: saveToast, showToast: showSaveToast } = useToast();
  const [logoutToast, setLogoutToast] = useState<ToastState>(TOAST_IDLE);

  function showSaved(currentLocale: string) {
    showSaveToast('success', t('saved', currentLocale));
  }

  function showSaveError(err: unknown, currentLocale: string) {
    showSaveToast('error', err instanceof ApiError ? err.message : t('save_failed', currentLocale));
  }

  const { locale, handleLocaleChange, isPending: localePending } = useLocaleMutation(
    ['settings'],
    {
      onSuccess: () => showSaved(getLocale()),
      onError: (err) => showSaveError(err, getLocale()),
    },
  );

  const digestMutation = useMutation({
    mutationFn: (optIn: boolean) =>
      api.patch<SettingsData>('/users/me', { email_digest_opt_in: optIn }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['settings'], updated);
      showSaved(locale);
    },
    onError: (err) => showSaveError(err, locale),
  });

  function handleOptInToggle(next: boolean) {
    digestMutation.mutate(next);
  }

  const logoutAllMutation = useMutation({
    mutationFn: () => api.post<{ detail: string }>('/auth/logout-all'),
    onSuccess: () => {
      setLogoutToast({ status: UI_STATE.success, message: t('logout_all_success', locale) });
      setTimeout(handleLogout, AUTH_REDIRECT_DELAY_MS);
    },
    onError: (err) => {
      setLogoutToast({
        status: UI_STATE.error,
        message: err instanceof ApiError ? err.message : t('logout_all_failed', locale),
      });
    },
  });

  function handleLogoutAll() {
    setLogoutToast(TOAST_IDLE);
    logoutAllMutation.mutate();
  }

  function personaEmoji(slug: string): string {
    return PERSONAS.find((p) => p.slug === slug)?.emoji ?? '◉';
  }

  const RANK_LABEL_KEYS = ['persona_primary', 'persona_secondary', 'persona_tertiary'] as const;

  if (isLoading) {
    return <PageState kind={UI_STATE.loading} message={t('loading', locale)} />;
  }

  if (isError) {
    return <PageState kind={UI_STATE.error} message={t('settings_error', locale)} />;
  }

  return (
    <div className={styles.page}>
      {saveToast.status !== UI_STATE.idle && <Toast status={saveToast.status} message={saveToast.message} />}

      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} localeDisabled={localePending} />

      <main className={styles.main}>
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_account', locale)}</h2>
          <p className={styles.email}>{data?.email}</p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_language', locale)}</h2>
          <div className={styles.localeControl}>
            <LocaleSelector
              locale={locale}
              onChange={handleLocaleChange}
              ariaLabel={t('section_language', locale)}
              disabled={localePending}
            />
          </div>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_persona', locale)}</h2>
          <div className={styles.personaDisplay}>
            {data?.personas.length ? (
              data.personas.map((p, i) => (
                <div className={styles.personaRow} key={p.slug}>
                  <span className={styles.personaEmoji}>{personaEmoji(p.slug)}</span>
                  <div>
                    <span className={styles.personaName}>
                      {personaName(p.slug, locale)}
                    </span>
                    <span className={cx(styles.personaBadge, i > 0 && styles.secondaryBadge)}>
                      {t(RANK_LABEL_KEYS[i] ?? RANK_LABEL_KEYS[RANK_LABEL_KEYS.length - 1], locale)}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <p className={styles.noPersona}>{t('no_persona', locale)}</p>
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
            <Toggle
              on={data?.email_digest_opt_in ?? false}
              onChange={handleOptInToggle}
              disabled={digestMutation.isPending}
              ariaLabel={data?.email_digest_opt_in ? t('digest_unsubscribe', locale) : t('digest_subscribe', locale)}
            />
          </div>
          {!data?.email_digest_opt_in && (
            <p className={styles.unsubMsg}>{t('digest_off', locale)}</p>
          )}
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_security', locale)}</h2>
          <div className={styles.toggleRow}>
            <div>
              <p className={styles.toggleLabel}>{t('logout_all_label', locale)}</p>
              <p className={styles.toggleDesc}>{t('logout_all_desc', locale)}</p>
            </div>
          </div>
          <button
            className={styles.repickBtn}
            onClick={handleLogoutAll}
            disabled={logoutAllMutation.isPending}
          >
            {t('logout_all_btn', locale)}
          </button>
          {logoutToast.status === UI_STATE.success && <p className={styles.saveSuccess} role="status">{logoutToast.message}</p>}
          {logoutToast.status === UI_STATE.error && <p className={styles.saveError} role="alert">{logoutToast.message}</p>}
        </section>
      </main>
    </div>
  );
}
