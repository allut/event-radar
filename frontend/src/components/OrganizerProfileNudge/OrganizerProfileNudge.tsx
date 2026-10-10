import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import { useLocalePath } from '../../hooks/useLocalePath';
import { t } from '../../i18n';
import { storageGet, storageSet } from '../../lib/storage';
import { API, ORGANIZER_PROFILE_NUDGE_DISMISSED_KEY, QUERY_KEYS, ROUTES } from '../../constants';
import styles from './OrganizerProfileNudge.module.css';

interface OrganizerProfileNudgeProps {
  locale: string;
}

interface OrganizerProfileResponse {
  name: string | null;
}

function isDismissed(): boolean {
  return storageGet(ORGANIZER_PROFILE_NUDGE_DISMISSED_KEY) !== null;
}

// Nudges a first-time organizer (no display name set) toward /organizer/settings.
// Shown on the dashboard and submit form; never blocks submission. Dismissal
// is client-only (localStorage) — no backend field for it (#175).
export default function OrganizerProfileNudge({ locale }: OrganizerProfileNudgeProps) {
  const localePath = useLocalePath();
  const [dismissed, setDismissed] = useState(isDismissed);

  const { data } = useQuery({
    queryKey: [QUERY_KEYS.organizerProfile],
    queryFn: () => organizerApi.get<OrganizerProfileResponse>(API.organizerProfile),
  });

  if (dismissed || !data || data.name) return null;

  function handleDismiss() {
    // Blocked storage just means dismissal won't persist across reloads.
    storageSet(ORGANIZER_PROFILE_NUDGE_DISMISSED_KEY, '1');
    setDismissed(true);
  }

  return (
    <div className={styles.nudge} role="status">
      <span className={styles.message}>{t('organizer_nudge_message', locale)}</span>
      <div className={styles.actions}>
        <Link to={localePath(ROUTES.organizerSettings)} className={styles.cta}>
          {t('organizer_nudge_cta', locale)}
        </Link>
        <button
          type="button"
          className={styles.dismissBtn}
          onClick={handleDismiss}
          aria-label={t('organizer_nudge_dismiss', locale)}
        >
          ×
        </button>
      </div>
    </div>
  );
}
