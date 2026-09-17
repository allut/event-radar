import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { getLocale } from '../../lib/auth';
import { useLocaleMutation } from '../../hooks/useLocaleMutation';
import { useLocaleNavigate } from '../../hooks/useLocaleNavigate';
import { useLogout } from '../../hooks/useLogout';
import { useToast } from '../../hooks/useToast';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { API, AUTH_REDIRECT_DELAY_MS, GOOGLE_IDENTITY_PROVIDER, QUERY_KEYS, RANK_LABEL_KEYS, ROUTES, UI_STATE, TOAST_IDLE, type ToastState } from '../../constants';
import { apiErrorMessage, cx } from '../../utils';
import { t, personaName } from '../../i18n';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import Toggle from '../../components/Toggle';
import TopBar from '../../components/TopBar';
import SeoTags from '../../components/SeoTags';
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
  google_linked: boolean;
}

export default function Settings() {
  const navigate = useLocaleNavigate();
  const queryClient = useQueryClient();
  const handleLogout = useLogout();

  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.settings],
    queryFn: () => api.get<SettingsData>(API.me),
  });

  const { toast: saveToast, showToast: showSaveToast } = useToast();
  const [logoutToast, setLogoutToast] = useState<ToastState>(TOAST_IDLE);

  function showSaved(currentLocale: string) {
    showSaveToast(UI_STATE.success, t('saved', currentLocale));
  }

  function showSaveError(err: unknown, currentLocale: string) {
    showSaveToast(UI_STATE.error, apiErrorMessage(err, t('save_failed', currentLocale)));
  }

  const { locale, handleLocaleChange, isPending: localePending } = useLocaleMutation({
    onSuccess: () => showSaved(getLocale()),
    onError: (err) => showSaveError(err, getLocale()),
  });
  const seoMeta = useStaticSeoMeta('seo_title_settings', locale);

  const digestMutation = useMutation({
    mutationFn: (optIn: boolean) =>
      api.patch<SettingsData>(API.me, { email_digest_opt_in: optIn }),
    onSuccess: (updated) => {
      queryClient.setQueryData([QUERY_KEYS.settings], updated);
      showSaved(locale);
    },
    onError: (err) => showSaveError(err, locale),
  });

  function handleOptInToggle(next: boolean) {
    digestMutation.mutate(next);
  }

  const logoutAllMutation = useMutation({
    mutationFn: () => api.post<{ detail: string }>(API.authLogoutAll),
    onSuccess: () => {
      setLogoutToast({ status: UI_STATE.success, message: t('logout_all_success', locale) });
      setTimeout(handleLogout, AUTH_REDIRECT_DELAY_MS);
    },
    onError: (err) => {
      setLogoutToast({
        status: UI_STATE.error,
        message: apiErrorMessage(err, t('logout_all_failed', locale)),
      });
    },
  });

  function handleLogoutAll() {
    setLogoutToast(TOAST_IDLE);
    logoutAllMutation.mutate();
  }

  const unlinkGoogleMutation = useMutation({
    mutationFn: () => api.delete<{ detail: string }>(API.meIdentity(GOOGLE_IDENTITY_PROVIDER)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.settings] });
      showSaveToast(UI_STATE.success, t('settings.identities.googleNotLinked', locale));
    },
    onError: (err) => showSaveError(err, locale),
  });

  if (isLoading) {
    return (
      <>
        <SeoTags meta={seoMeta} />
        <PageState kind={UI_STATE.loading} message={t('loading', locale)} />
      </>
    );
  }

  if (isError) {
    return (
      <>
        <SeoTags meta={seoMeta} />
        <PageState kind={UI_STATE.error} message={t('settings_error', locale)} />
      </>
    );
  }

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      {saveToast.status !== UI_STATE.idle && <Toast status={saveToast.status} message={saveToast.message} />}

      <TopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} localeDisabled={localePending} />

      <main className={styles.main}>
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_account', locale)}</h2>
          <p className={styles.email}>{data?.email}</p>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_persona', locale)}</h2>
          <div className={styles.personaDisplay}>
            {data?.personas.length ? (
              data.personas.map((p, i) => (
                <div className={styles.personaRow} key={p.slug}>
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
            onClick={() => navigate(ROUTES.onboarding)}
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

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('section_identities', locale)}</h2>
          <div className={styles.toggleRow}>
            <div>
              <p className={styles.toggleLabel}>
                {t(data?.google_linked ? 'settings.identities.googleLinked' : 'settings.identities.googleNotLinked', locale)}
              </p>
            </div>
          </div>
          {data?.google_linked && (
            <button
              className={styles.repickBtn}
              onClick={() => unlinkGoogleMutation.mutate()}
              disabled={unlinkGoogleMutation.isPending}
            >
              {t('settings.identities.unlinkGoogle', locale)}
            </button>
          )}
        </section>
      </main>
    </div>
  );
}
