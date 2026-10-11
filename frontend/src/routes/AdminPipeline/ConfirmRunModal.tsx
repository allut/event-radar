import { useState } from 'react';
import Modal from '../../components/Modal';
import type { AdminPipelineTrigger } from '../../constants/admin';
import { LOCALE_EN } from '../../constants/core';
import type { NdjsonLine } from '../../api/client';
import styles from './ConfirmRunModal.module.css';

interface ConfirmRunModalProps {
  trigger: AdminPipelineTrigger;
  /** The completed dry run's streamed lines, when this modal was opened from
   * a "Run for real" button — carries those numbers into the confirmation
   * (issue #160). Null when opened directly (dry run toggled off, no prior
   * dry run this session). */
  dryRunLines: NdjsonLine[] | null;
  onCancel: () => void;
  onConfirm: () => void;
}

/** Two-step typed-confirmation modal (issue #160) gating a real (dry_run=false)
 * run of cleanup/send-digests/pipeline-run: a warning screen naming the
 * specific consequence, then a second screen with the dry run's numbers (if
 * any) and a plain Confirm button. */
export default function ConfirmRunModal({ trigger, dryRunLines, onCancel, onConfirm }: ConfirmRunModalProps) {
  const [step, setStep] = useState<1 | 2>(1);

  return (
    <Modal admin open onClose={onCancel} title={step === 1 ? 'This is a real run' : `Confirm ${trigger.label.toLowerCase()}`} locale={LOCALE_EN}>
      {step === 1 ? (
        <>
          <p className={styles.danger} role="alert">{trigger.dangerCopy}</p>
          <div className={styles.actions}>
            <button type="button" className={styles.cancelBtn} onClick={onCancel}>Cancel</button>
            <button type="button" className={styles.continueBtn} onClick={() => setStep(2)}>I understand, continue</button>
          </div>
        </>
      ) : (
        <>
          {dryRunLines && dryRunLines.length > 0 && (
            <div className={styles.numbers}>
              <div className={styles.numbersHead}>Dry run found:</div>
              {dryRunLines.map((l) => (
                <pre key={l.stage} className={styles.numbersPre}>{JSON.stringify(l.status === 'ok' ? l.result : l.error, null, 2)}</pre>
              ))}
            </div>
          )}
          <div className={styles.actions}>
            <button type="button" className={styles.cancelBtn} onClick={onCancel}>Cancel</button>
            <button type="button" className={styles.confirmBtn} onClick={onConfirm}>Run for real</button>
          </div>
        </>
      )}
    </Modal>
  );
}
