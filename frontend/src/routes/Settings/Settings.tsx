import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '../../api/client';
import { clearToken, getLocale } from '../../lib/auth';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { AUTH_REDIRECT_DELAY_MS, PERSONAS, SAVE_MSG_CLEAR_DELAY_MS, PERSONA_PRIMARY_WEIGHT_THRESHOLD } from '../../constants';
import { cx } from '../../utils';
import { t, personaName } from '../../i18n';
import LocaleSelector from '../../components/LocaleSelector';
import PageState from '../../components/PageState';
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

type Toast = { status: 'idle' } | { status: 'success' | 'error'; message: string };

const TOAST_IDLE: Toast = { status: 'idle' };

export default function Settings() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get<SettingsData>('/users/me'),
  });

  const [saveToast, setSaveToast] = useState<Toast>(TOAST_IDLE);
  const [logoutToast, setLogoutToast] = useState<Toast>(TOAST_IDLE);

  function showSaved(currentLocale: string) {
    setSaveToast({ status: 'success', message: t('saved', currentLocale) });
    setTimeout(() => setSaveToast(TOAST_IDLE), SAVE_MSG_CLEAR_DELAY_MS);
  }

  function showSaveError(err: unknown, currentLocale: string) {
    setSaveToast({
      status: 'error',
      message: err instanceof ApiError ? err.message : t('save_failed', currentLocale),
    });
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
      setLogoutToast({ status: 'success', message: t('logout_all_success', locale) });
      setTimeout(() => {
        clearToken();
        queryClient.clear();
        navigate('/login', { replace: true });
      }, AUTH_REDIRECT_DELAY_MS);
    },
    onError: (err) => {
      setLogoutToast({
        status: 'error',
        message: err instanceof ApiError ? err.message : t('logout_all_failed', locale),
      });
    },
  });

  function handleLogoutAll() {
    setLogoutToast(TOAST_IDLE);
    logoutAllMutation.mutate();
  }

  function handleLogout() {
    clearToken();
    queryClient.clear();
    navigate('/login', { replace: true });
  }

  const primaryPersona = data?.personas.find((p) => p.weight >= PERSONA_PRIMARY_WEIGHT_THRESHOLD);
  const secondaryPersona = data?.personas.find((p) => p.weight < PERSONA_PRIMARY_WEIGHT_THRESHOLD);

  function personaEmoji(slug: string): string {
    return PERSONAS.find((p) => p.slug === slug)?.emoji ?? '◉';
  }

  if (isLoading) {
    return <PageState kind="loading" message={t('loading', locale)} />;
  }

  if (isError) {
    return <PageState kind="error" message={t('settings_error', locale)} />;
  }

  return (
    <div className={styles.page}>
      {saveToast.status === 'success' && <div className={styles.toastSuccess} role="status">{saveToast.message}</div>}
      {saveToast.status === 'error' && <div className={styles.toastError} role="alert">{saveToast.message}</div>}

      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} localeDisabled={localePending} />

      <main className={styles.main}>
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_account', locale)}</h2>
          <p className={styles.email}>{data?.email}</p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_language', locale)}</h2>
          <LocaleSelector
            locale={locale}
            onChange={handleLocaleChange}
            ariaLabel={t('section_language', locale)}
            disabled={localePending}
          />
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
                  <span className={cx(styles.personaBadge, styles.secondaryBadge)}>{t('persona_secondary', locale)}</span>
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
          {logoutToast.status === 'success' && <p className={styles.saveSuccess} role="status">{logoutToast.message}</p>}
          {logoutToast.status === 'error' && <p className={styles.saveError} role="alert">{logoutToast.message}</p>}
        </section>
      </main>
    </div>
  );
}
