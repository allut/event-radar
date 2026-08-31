import { ADMIN_NOTE_TEXTAREA_ROWS } from '../../constants';
import styles from './AdminQueueActionPanel.module.css';

interface AdminQueueAction {
  label: string;
  onClick: () => void;
  variant: 'primary' | 'danger';
  disabled?: boolean;
}

interface AdminQueueActionPanelProps {
  noteValue: string;
  onNoteChange: (value: string) => void;
  noteLabel: string;
  noteDisabled: boolean;
  actions: AdminQueueAction[];
  hint?: string;
}

/** Inline resolve/takedown-style action panel — note field directly under
 * the buttons, no dialog (issue #142/#155). Shared by every admin queue
 * detail panel (reports today; submissions and the event inspector reuse
 * it next) so the note-plus-buttons treatment stays one component. */
export default function AdminQueueActionPanel({
  noteValue,
  onNoteChange,
  noteLabel,
  noteDisabled,
  actions,
  hint,
}: AdminQueueActionPanelProps) {
  return (
    <div className={styles.panel}>
      <label className={styles.noteField}>
        <span className={styles.noteLabel}>{noteLabel}</span>
        <textarea
          className={styles.noteTextarea}
          value={noteValue}
          onChange={(e) => onNoteChange(e.target.value)}
          rows={ADMIN_NOTE_TEXTAREA_ROWS}
          disabled={noteDisabled}
        />
      </label>
      <div className={styles.actions}>
        {actions.map((action) => (
          <button
            key={action.label}
            type="button"
            className={action.variant === 'primary' ? styles.primaryBtn : styles.dangerBtn}
            disabled={action.disabled}
            onClick={action.onClick}
          >
            {action.label}
          </button>
        ))}
      </div>
      {hint && <p className={styles.hint}>{hint}</p>}
    </div>
  );
}
