import { Link } from 'react-router-dom';
import { cx } from '../../utils';
import styles from './PromotionResultCard.module.css';

interface PromotionResultCardProps {
  /** A check in a ring, or a spinner while the result is still coming. */
  icon: 'check' | 'spinner';
  title: string;
  message: string;
  /** The summary rows under the message. */
  recap?: ReadonlyArray<{ label: string; value: string }>;
  footnote?: string;
  /** The buttons row; the primary one is the filled call to action. */
  links?: ReadonlyArray<{ label: string; to?: string; onClick?: () => void; primary?: boolean }>;
  /** Announced politely: for a result that appears or changes after load. */
  live?: boolean;
}

/** The centred result card of a Promotion flow: request sent, payment received
 * or still confirming. The accent top rule and ring icon follow AuthCard's status look. */
export default function PromotionResultCard({ icon, title, message, recap, footnote, links, live }: PromotionResultCardProps) {
  return (
    <div className={styles.card} role={live ? 'status' : undefined}>
      {icon === 'check' ? (
        <div className={styles.circle} aria-hidden="true">✓</div>
      ) : (
        <span className={styles.spinner} aria-hidden="true" />
      )}
      <h1 className={styles.title}>{title}</h1>
      <p className={styles.message}>{message}</p>
      {recap && recap.length > 0 && (
        <dl className={styles.recap}>
          {recap.map(({ label, value }) => (
            <div key={label} className={styles.recapRow}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {footnote && <p className={styles.footnote}>{footnote}</p>}
      {links && links.length > 0 && (
        <div className={styles.buttons}>
          {links.map(({ to, label, onClick, primary }) => {
            const className = cx(styles.link, primary ? styles.primary : styles.outline);
            return to ? (
              <Link key={label} to={to} className={className}>
                {label}
              </Link>
            ) : (
              <button key={label} type="button" className={className} onClick={onClick}>
                {label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
