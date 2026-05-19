import { SIGNAL_CONFIG, type Signal } from '../constants';
import { t } from '../i18n';
import { cx, makeActiveClassMap } from '../utils';
import styles from './FeedbackButtonRow.module.css';

const ACTIVE_CLASS = makeActiveClassMap(styles);

interface FeedbackButtonRowProps {
  activeSignal: Signal | null;
  pending: boolean;
  onPress: (signal: Signal) => void;
  locale: string;
  variant?: 'card' | 'detail';
}

export default function FeedbackButtonRow({
  activeSignal,
  pending,
  onPress,
  locale,
  variant = 'card',
}: FeedbackButtonRowProps) {
  return (
    <div className={styles.row}>
      {(Object.entries(SIGNAL_CONFIG) as [Signal, { icon: string; label: string }][]).map(([signal, { icon }]) => {
        const label = t(`signal_${signal}`, locale);
        return (
          <button
            key={signal}
            className={cx(
              styles.action,
              styles[variant],
              activeSignal === signal && ACTIVE_CLASS[signal],
            )}
            onClick={() => onPress(signal)}
            disabled={pending}
            aria-label={label}
            aria-pressed={activeSignal === signal}
            title={label}
          >
            {icon}
          </button>
        );
      })}
    </div>
  );
}
