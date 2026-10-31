import { useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useToast } from '../../hooks/useToast';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { t } from '../../i18n';
import { ORGANIZER_NAME_MAX_LEN } from '../../_generated/sharedConstants';
import { API, QUERY_KEYS } from '../../constants/api';
import { AUTH_REDIRECT_DELAY_MS, GOOGLE_IDENTITY_PROVIDER } from '../../constants/auth';
import { TOAST_IDLE, UI_STATE, type ToastState } from '../../constants/core';
import { apiErrorMessage } from '../../utils/apiErrors';
import SeoTags from '../../components/SeoTags';
import styles from './OrganizerSettings.module.css';

interface OrganizerProfileResponse {
  id: number;
  email: string;
  locale: string;
  verified: boolean;
  name: string | null;
  google_linked: boolean;
}

export default function OrganizerSettings() {
  const [locale, handleLocaleChange] = useLocalLocale();
  const handleLogout = useOrganizerLogout();
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const [logoutToast, setLogoutToast] = useState<ToastState>(TOAST_IDLE);
  const seoMeta = useStaticSeoMeta('organizer_settings_title', locale);
  const [name, setName] = useState('');

  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.organizerProfile],
    queryFn: () => organizerApi.get<OrganizerProfileResponse>(API.organizerProfile),
  });

  // One-time hydration from the fetched profile — deferred to a microtask
  // (mirrors useOrganizerEventForm.ts's prefill effect) since
  // react-hooks/set-state-in-effect flags a *synchronous* setState here.
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (!data || hydratedRef.current) return;
    hydratedRef.current = true;
    void Promise.resolve().then(() => setName(data.name ?? ''));
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: (nextName: string) =>
      organizerApi.patch<OrganizerProfileResponse>(API.organizerProfile, { name: nextName }),
    onSuccess: () => {
      // Refetch rather than write the mutation's own response into the cache
      // — a direct write can race unlinkGoogleMutation's write below and
      // clobber whichever field the other mutation just changed.
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerProfile] });
      showToast(UI_STATE.success, t('organizer_profile_saved', locale));
    },
    onError: (err) => {
      showToast(UI_STATE.error, apiErrorMessage(err, t('generic_error', locale)));
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    saveMutation.mutate(name);
  }

  const logoutAllMutation = useMutation({
    mutationFn: () => organizerApi.post<{ detail: string }>(API.organizerAuthLogoutAll),
    onSuccess: () => {
      setLogoutToast({ status: UI_STATE.success, message: t('organizer_logout_all_success', locale) });
      setTimeout(handleLogout, AUTH_REDIRECT_DELAY_MS);
    },
    onError: (err) => {
      setLogoutToast({
        status: UI_STATE.error,
        message: apiErrorMessage(err, t('organizer_logout_all_failed', locale)),
      });
    },
  });

  function handleLogoutAll() {
    setLogoutToast(TOAST_IDLE);
    logoutAllMutation.mutate();
  }

  const unlinkGoogleMutation = useMutation({
    mutationFn: () => organizerApi.delete<{ detail: string }>(API.organizerProfileIdentity(GOOGLE_IDENTITY_PROVIDER)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.organizerProfile] });
      showToast(UI_STATE.success, t('settings.identities.googleNotLinked', locale));
    },
    onError: (err) => {
      showToast(UI_STATE.error, apiErrorMessage(err, t('generic_error', locale)));
    },
  });

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      {isLoading ? (
        <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
      ) : isError ? (
        <PageState kind={UI_STATE.error} message={t('generic_error', locale)} inline />
      ) : (
        <main className={styles.main}>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t('organizer_section_account', locale)}</h2>
            <p className={styles.email}>{data?.email}</p>
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t('organizer_section_display_name', locale)}</h2>
            <form onSubmit={handleSubmit} className={styles.form} noValidate>
              <div className={styles.field}>
                <label htmlFor="organizer-name" className={styles.srOnly}>
                  {t('organizer_profile_name_label', locale)}
                </label>
                <input
                  id="organizer-name"
                  className={styles.input}
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t('organizer_profile_name_placeholder', locale)}
                  maxLength={ORGANIZER_NAME_MAX_LEN}
                />
              </div>
              <button type="submit" className={styles.saveBtn} disabled={saveMutation.isPending}>
                {t('organizer_profile_save', locale)}
              </button>
            </form>
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t('organizer_section_security', locale)}</h2>
            <div className={styles.toggleRow}>
              <div>
                <p className={styles.toggleLabel}>{t('organizer_logout_all_label', locale)}</p>
                <p className={styles.toggleDesc}>{t('organizer_logout_all_desc', locale)}</p>
              </div>
            </div>
            <button
              className={styles.repickBtn}
              onClick={handleLogoutAll}
              disabled={logoutAllMutation.isPending}
            >
              {t('organizer_logout_all_btn', locale)}
            </button>
            {logoutToast.status === UI_STATE.success && <p className={styles.saveSuccess} role="status">{logoutToast.message}</p>}
            {logoutToast.status === UI_STATE.error && <p className={styles.saveError} role="alert">{logoutToast.message}</p>}
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t('organizer_section_identities', locale)}</h2>
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
      )}

      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}
