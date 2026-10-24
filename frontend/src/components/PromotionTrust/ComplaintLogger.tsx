import { useId, useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import { ADMIN_GENERIC_ERROR } from '../../constants/admin';
import { API, QUERY_KEYS } from '../../constants/api';
import {
  PROMOTION_COMPLAINT_NOTE_MAX,
  PROMOTION_COMPLAINT_NOTE_ROWS,
  PROMOTION_COMPLAINT_SOURCES,
  PROMOTION_COMPLAINT_SOURCE_DEFAULT,
  PROMOTION_TRUST_COPY as COPY,
} from '../../constants/promotions';
import { formatDateTime, type PromotionComplaint } from '../../lib/promotions';
import { apiErrorMessage } from '../../utils';
import SelectField from '../SelectField';
import styles from './PromotionTrust.module.css';

const SOURCE_LABELS: Record<string, string> = Object.fromEntries(PROMOTION_COMPLAINT_SOURCES.map((s) => [s.value, s.label]));

/** Log a complaint about the ads (#620) and list the newest ones. The note is
 * required; the complainant is optional so two complaints from one person can
 * be told apart. Audited server side and counted in the Trust panel. */
export default function ComplaintLogger({ complaints }: { complaints: PromotionComplaint[] }) {
  const queryClient = useQueryClient();
  const id = useId();
  const [source, setSource] = useState<string>(PROMOTION_COMPLAINT_SOURCE_DEFAULT);
  const [who, setWho] = useState('');
  const [note, setNote] = useState('');
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  const log = useMutation({
    mutationFn: (body: { source: string; complainant: string | null; note: string }) =>
      adminApi.post(API.adminPromotionComplaints, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEYS.adminPromotionTrust] });
      setNote('');
      setWho('');
      setMessage({ text: COPY.complaintLogged, ok: true });
    },
    onError: (err) => setMessage({ text: apiErrorMessage(err, ADMIN_GENERIC_ERROR), ok: false }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const text = note.trim();
    if (!text) return setMessage({ text: COPY.complaintNoteRequired, ok: false });
    setMessage(null);
    log.mutate({ source, complainant: who.trim() || null, note: text });
  }

  const noteMissing = message !== null && !message.ok && message.text === COPY.complaintNoteRequired;

  return (
    <section aria-labelledby="complaint-heading">
      <h2 id="complaint-heading" className={styles.sectionTitle}>{COPY.complaintHeading}</h2>
      <form className={styles.logger} onSubmit={submit} noValidate>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${id}-src`}>{COPY.complaintSource}</label>
          <SelectField
            id={`${id}-src`}
            ariaLabel={COPY.complaintSource}
            placeholder={COPY.complaintSource}
            value={source}
            options={PROMOTION_COMPLAINT_SOURCES.map((s) => ({ value: s.value, label: s.label }))}
            onChange={(v) => v && setSource(v)}
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor={`${id}-who`}>{COPY.complaintWho}</label>
          <input
            id={`${id}-who`}
            className={`${styles.input} ${styles.loggerInput}`}
            placeholder={COPY.complaintWhoPlaceholder}
            value={who}
            onChange={(e) => setWho(e.target.value)}
          />
        </div>
        <div className={`${styles.field} ${styles.wide}`}>
          <label className={styles.label} htmlFor={`${id}-note`}>{COPY.complaintNote}</label>
          <textarea
            id={`${id}-note`}
            className={styles.input}
            rows={PROMOTION_COMPLAINT_NOTE_ROWS}
            maxLength={PROMOTION_COMPLAINT_NOTE_MAX}
            placeholder={COPY.complaintNotePlaceholder}
            value={note}
            aria-invalid={noteMissing ? true : undefined}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        <div className={`${styles.wide} ${styles.loggerBar}`}>
          <button type="submit" className={styles.primaryButton} disabled={log.isPending}>{COPY.complaintSubmit}</button>
          <span className={styles.hint}>{COPY.complaintAudit}</span>
        </div>
        {message && (
          <p className={`${message.ok ? styles.okmsg : styles.error} ${styles.wide}`} role={message.ok ? 'status' : 'alert'}>
            {message.text}
          </p>
        )}
      </form>

      <h3 className={`${styles.sectionTitle} ${styles.recentTitle}`}>{COPY.recentHeading}</h3>
      <ul className={styles.rows}>
        {complaints.length === 0 ? (
          <li className={styles.muted}>{COPY.noComplaints}</li>
        ) : (
          complaints.map((c) => (
            <li key={c.id}>
              <div className={styles.rowMeta}>
                <span className={styles.mono}>{formatDateTime(c.created_at)}</span>
                <span className={styles.chip}>{(c.source && SOURCE_LABELS[c.source]) ?? c.source ?? '—'}</span>
                <span>{c.complainant ?? COPY.noName}</span>
              </div>
              <div>{c.note}</div>
            </li>
          ))
        )}
      </ul>
    </section>
  );
}
