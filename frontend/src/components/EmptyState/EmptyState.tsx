import styles from './EmptyState.module.css';

interface EmptyStateProps {
  title: string;
  message: string;
  hint?: string;
  /** Small-caps label above the hairline — an existing i18n string reused
   * from the surrounding route, not new copy (wayfinder #197). */
  eyebrow?: string;
}

export default function EmptyState({ title, message, hint, eyebrow }: EmptyStateProps) {
  return (
    <div className={styles.empty}>
      {eyebrow && <p className={styles.emptyEyebrow}>{eyebrow}</p>}
      <div className={styles.emptyHair} />
      <h2 className={styles.emptyTitle}>{title}</h2>
      <p className={styles.emptyMsg}>{message}</p>
      {hint && <p className={styles.emptyHint}>{hint}</p>}
    </div>
  );
}
