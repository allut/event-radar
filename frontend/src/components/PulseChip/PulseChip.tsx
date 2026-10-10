import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { API, EXPLORE_TODAY_SEARCH, QUERY_KEYS, ROUTES } from '../../constants';
import { t } from '../../i18n';
import { withLocaleQuery } from '../../utils';
import { useLocalePath } from '../../hooks/useLocalePath';
import styles from '../shared/Bar.module.css';

interface PulseChipProps {
  locale: string;
}

interface CountsResponse {
  today_count?: number;
}

// Shares Landing's [counts, locale] query. `today_count` is exactly what the
// chip's link (/explore?date=today) lands on.
export default function PulseChip({ locale }: PulseChipProps) {
  const localePath = useLocalePath();
  const { data } = useQuery({
    queryKey: [QUERY_KEYS.counts, locale],
    queryFn: () => api.get<CountsResponse>(withLocaleQuery(API.publicCounts, locale)),
    retry: false,
  });
  const count = data?.today_count ?? 0;
  const [before, after] = t('bar_pulse_today', locale).split('{count}');
  // The slot is always rendered so the chip's arrival (after JS + fetch, never
  // in prerendered HTML) shifts nothing; it fades in once the count is known.
  return (
    <span className={styles.pulseSlot}>
      {count > 0 && (
        <Link to={`${localePath(ROUTES.explore)}${EXPLORE_TODAY_SEARCH}`} className={styles.pulse}>
          <span>{before}<b>{count}</b>{after ?? ''}</span>
        </Link>
      )}
    </span>
  );
}
