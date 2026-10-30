import { useQuery } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import { API, QUERY_KEYS } from '../../constants/api';
import { UI_STATE } from '../../constants/core';
import { PROMOTION_COPY } from '../../constants/promotions';
import type { PromotionContext } from '../../lib/promotions';
import PromotionGrantForm from '../../components/PromotionGrantForm';
import PromotionsTable from '../../components/PromotionsTable';
import styles from './AdminEventDetail.module.css';

interface PromotionsPanelProps {
  eventId: string;
  onNotify: (status: typeof UI_STATE.success | typeof UI_STATE.error, message: string) => void;
}

// The event's Promotions tab (#600): its existing Promotions, then the
// Grant Promotion form. Shares the form's context query, so one request.
export default function PromotionsPanel({ eventId, onNotify }: PromotionsPanelProps) {
  const { data } = useQuery({
    queryKey: [QUERY_KEYS.adminPromotionContext, eventId],
    queryFn: () => adminApi.get<PromotionContext>(API.adminPromotionContext(eventId)),
  });
  const existing = data?.promotions ?? [];

  return (
    <>
      <div className={styles.subsection}>
        <h3 className={styles.subsectionTitle}>Promotions ({existing.length})</h3>
        {existing.length === 0 ? (
          <p className={styles.empty}>{PROMOTION_COPY.noPromotions}</p>
        ) : (
          <PromotionsTable rows={existing} />
        )}
      </div>
      <div className={styles.subsection}>
        <h3 className={styles.subsectionTitle}>{PROMOTION_COPY.grantHeading}</h3>
        <PromotionGrantForm eventId={eventId} onNotify={onNotify} />
      </div>
    </>
  );
}
