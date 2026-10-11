import { useQuery } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import { API, QUERY_KEYS } from '../../constants/api';
import { padIndex } from '../../utils';
import styles from './AdminDashboard.module.css';

interface AdminCounts {
  open_reports: number;
  pending_submissions: number;
  pending_claims: number;
}

function padCount(n: number | undefined): string {
  return n === undefined ? '––' : padIndex(n);
}

// Admin console landing screen (issue #154, extended #420) — the counts GET
// /admin/counts returns. This is eyeballing only; the Reports/Submissions/
// Claims queues themselves are the dedicated screens.
export default function AdminDashboard() {
  const { data, isLoading } = useQuery({
    queryKey: [QUERY_KEYS.adminCounts],
    queryFn: () => adminApi.get<AdminCounts>(API.adminCounts),
  });

  return (
    <div>
      <div className={styles.head}>
        <p className={styles.eyebrow}>Admin / Overview</p>
        <h1 className={styles.title}>Dashboard</h1>
      </div>

      <div className={styles.tiles}>
        <div className={`${styles.tile} ${(data?.open_reports ?? 0) > 0 ? styles.tileWarn : ''}`}>
          <p className={styles.tileLabel}>Open reports</p>
          <p className={styles.tileNum}>{isLoading ? '··' : padCount(data?.open_reports)}</p>
          <p className={styles.tileSub}>awaiting moderation review</p>
        </div>
        <div className={styles.tile}>
          <p className={styles.tileLabel}>Pending submissions</p>
          <p className={styles.tileNum}>{isLoading ? '··' : padCount(data?.pending_submissions)}</p>
          <p className={styles.tileSub}>organizer events needing eyeball</p>
        </div>
        <div className={styles.tile}>
          <p className={styles.tileLabel}>Pending claims</p>
          <p className={styles.tileNum}>{isLoading ? '··' : padCount(data?.pending_claims)}</p>
          <p className={styles.tileSub}>awaiting grant/decline</p>
        </div>
      </div>
    </div>
  );
}
