import { useEffect, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { organizerApi, ApiError } from '../../api/client';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useToast } from '../../hooks/useToast';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import PageState from '../../components/PageState';
import Toast from '../../components/Toast';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { t } from '../../i18n';
import { API, ORGANIZER_NAME_MAX_LEN, QUERY_KEYS, UI_STATE } from '../../constants';
import SeoTags from '../../components/SeoTags';
import styles from './OrganizerProfile.module.css';

interface OrganizerProfileResponse {
  id: number;
  email: string;
  locale: string;
  verified: boolean;
  name: string | null;
}

export default function OrganizerProfile() {
  const [locale, handleLocaleChange] = useLocalLocale();
  const handleLogout = useOrganizerLogout();
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const seoMeta = useStaticSeoMeta('organizer_profile_title', locale);
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
    onSuccess: (updated) => {
      queryClient.setQueryData([QUERY_KEYS.organizerProfile], updated);
      showToast(UI_STATE.success, t('organizer_profile_saved', locale));
    },
    onError: (err) => {
      showToast(UI_STATE.error, err instanceof ApiError ? err.message : t('generic_error', locale));
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    saveMutation.mutate(name);
  }

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <h1 className={styles.heading}>{t('organizer_profile_title', locale)}</h1>

        {isLoading ? (
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        ) : isError ? (
          <PageState kind={UI_STATE.error} message={t('generic_error', locale)} inline />
        ) : (
          <form onSubmit={handleSubmit} className={styles.form} noValidate>
            <div className={styles.field}>
              <label htmlFor="organizer-name" className={styles.label}>
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
        )}
      </main>

      {toast.status !== UI_STATE.idle && <Toast status={toast.status} message={toast.message} />}
    </div>
  );
}
