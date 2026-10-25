import { useState } from 'react';
import { api } from '../../api/client';
import { t, ti } from '../../i18n';
import { REPORT_DETAIL_MAX_CHARS } from '../../_generated/sharedConstants';
import { API } from '../../constants/api';
import {
  REPORT_DETAIL_TEXTAREA_ROWS,
  REPORT_REASON_OTHER,
  REPORT_REASONS,
} from '../../constants/feedback';
import { apiErrorMessage } from '../../utils';
import Modal from '../Modal';
import styles from './ReportModal.module.css';

interface ReportModalProps {
  open: boolean;
  onClose: () => void;
  eventId: number;
  locale: string;
  /** Called once the report is durably recorded — lets the caller flip its
   * local "reported" state and invalidate the feed/explore/saved/event caches. */
  onSubmitted: () => void;
}

/** First Modal-based flow in this codebase (issue #128): reason picker, an
 * illegal-content checkbox, and a free-text detail field, required whenever
 * the reason is "other" or the illegal checkbox is checked — mirrors the
 * backend's own validation in routers/reports.py. Callers mount this only
 * while `open` is true (conditional render, not a hidden-but-mounted panel),
 * so each open starts from fresh form state with no reset effect needed. */
export default function ReportModal({ open, onClose, eventId, locale, onSubmitted }: ReportModalProps) {
  const [reason, setReason] = useState<string | null>(null);
  const [isIllegal, setIsIllegal] = useState(false);
  const [detail, setDetail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const detailRequired = reason === REPORT_REASON_OTHER || isIllegal;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!reason) {
      setError(t('report_reason_required_error', locale));
      return;
    }
    const trimmedDetail = detail.trim();
    if (detailRequired && !trimmedDetail) {
      setError(t('report_detail_required_error', locale));
      return;
    }
    if (trimmedDetail.length > REPORT_DETAIL_MAX_CHARS) {
      setError(ti('report_detail_too_long_error', locale, { max_chars: String(REPORT_DETAIL_MAX_CHARS) }));
      return;
    }

    setError(null);
    setSubmitting(true);
    try {
      await api.post(API.reports, {
        event_id: eventId,
        reason,
        is_illegal_allegation: isIllegal,
        detail: trimmedDetail || undefined,
      });
      setSubmitted(true);
      onSubmitted();
    } catch (err) {
      setError(apiErrorMessage(err, t('report_submit_failed', locale)));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={t('report_event', locale)} locale={locale}>
      {submitted ? (
        <div className={styles.confirmation}>
          <p>{t('report_confirmation', locale)}</p>
          <button type="button" className={styles.doneBtn} onClick={onClose}>
            {t('close', locale)}
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit}>
          <fieldset className={styles.reasonGroup}>
            <legend className={styles.label}>{t('report_modal_reason_label', locale)}</legend>
            {REPORT_REASONS.map((r) => (
              <label key={r.value} className={styles.reasonOption}>
                <input
                  type="radio"
                  name="report-reason"
                  value={r.value}
                  checked={reason === r.value}
                  onChange={() => setReason(r.value)}
                />
                <span className={styles.reasonText}>
                  <span className={styles.reasonLabel}>{t(r.labelKey, locale)}</span>
                  <span className={styles.reasonDescription}>{t(r.descriptionKey, locale)}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <label className={styles.illegalOption}>
            <input
              type="checkbox"
              checked={isIllegal}
              onChange={(e) => setIsIllegal(e.target.checked)}
            />
            <span>{t('report_illegal_checkbox', locale)}</span>
          </label>

          <label className={styles.detailField}>
            <span className={styles.label}>
              {t('report_detail_label', locale)}
              {!detailRequired && <span className={styles.optional}> ({t('optional', locale)})</span>}
            </span>
            <textarea
              className={styles.textarea}
              value={detail}
              onChange={(e) => setDetail(e.target.value)}
              placeholder={t('report_detail_placeholder', locale)}
              maxLength={REPORT_DETAIL_MAX_CHARS}
              rows={REPORT_DETAIL_TEXTAREA_ROWS}
            />
          </label>

          {error && <p className={styles.error}>{error}</p>}

          <div className={styles.actions}>
            <button type="button" className={styles.cancelBtn} onClick={onClose} disabled={submitting}>
              {t('report_cancel', locale)}
            </button>
            <button type="submit" className={styles.submitBtn} disabled={submitting}>
              {t('report_submit', locale)}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
