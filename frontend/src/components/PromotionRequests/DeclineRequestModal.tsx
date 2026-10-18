import { useId, useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import { ADMIN_GENERIC_ERROR } from '../../constants/admin';
import { API, QUERY_KEYS } from '../../constants/api';
import { LOCALE_EN } from '../../constants/core';
import {
  PROMOTION_DECLINE_REASON_MAX,
  PROMOTION_DECLINE_ROWS,
  PROMOTION_REQUEST_COPY as COPY,
} from '../../constants/promotions';
import type { PromotionRequestRow } from '../../lib/promotions';
import { apiErrorMessage } from '../../utils';
import Modal from '../Modal';
import styles from './PromotionRequests.module.css';

interface DeclineRequestModalProps {
  request: PromotionRequestRow;
  onClose: () => void;
  onDeclined: (request: PromotionRequestRow) => void;
}

/** Decline a pending request (#615). The reason is required: it is emailed to
 * the Organizer in their locale, so the dialog says where it goes. */
export default function DeclineRequestModal({ request, onClose, onDeclined }: DeclineRequestModalProps) {
  const queryClient = useQueryClient();
  const id = useId();
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);

  const decline = useMutation({
    mutationFn: (text: string) => adminApi.post(API.adminPromotionRequestDecline(request.id), { reason: text }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionRequests] });
      onDeclined(request);
    },
    onError: (err) => {
      setError(apiErrorMessage(err, ADMIN_GENERIC_ERROR));
      // Another admin may have resolved it first: refresh the queue behind the dialog.
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionRequests] });
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const text = reason.trim();
    if (!text) return setError(COPY.declineReasonRequired);
    setError(null);
    decline.mutate(text);
  }

  return (
    <Modal admin open onClose={onClose} title={COPY.declineHeading(request.event_title)} locale={LOCALE_EN}>
      <form className={styles.declineForm} onSubmit={submit} noValidate>
        <p className={styles.declineTo}>{COPY.declineTo(request.organizer_email)}</p>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${id}-reason`}>{COPY.declineReasonLabel}</label>
          <textarea
            id={`${id}-reason`}
            className={styles.input}
            rows={PROMOTION_DECLINE_ROWS}
            maxLength={PROMOTION_DECLINE_REASON_MAX}
            value={reason}
            aria-invalid={error === COPY.declineReasonRequired ? true : undefined}
            onChange={(e) => setReason(e.target.value)}
          />
          <span className={styles.hint}>{reason.length} / {PROMOTION_DECLINE_REASON_MAX}</span>
        </div>
        <p className={styles.error} role="alert">{error}</p>
        <div className={styles.panelButtons}>
          <button type="submit" className={styles.dangerButton} disabled={decline.isPending}>{COPY.declineConfirm}</button>
          <button type="button" className={styles.plainButton} onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Modal>
  );
}
