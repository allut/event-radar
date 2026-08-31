import { useState } from 'react';
import { cx } from '../../utils';
import styles from './AdminQueueSplitView.module.css';

interface AdminQueueSplitViewProps<T> {
  items: T[];
  getId: (item: T) => number;
  isResolved: (item: T) => boolean;
  resolvedTag: (item: T) => string;
  selectedId: number | null;
  onSelect: (id: number) => void;
  renderRow: (item: T) => React.ReactNode;
  renderDetail: (item: T) => React.ReactNode;
  emptyLabel: string;
  /** Open the detail panel on mobile from first render (e.g. a caller that
   * seeded `selectedId` from a deep link, where the row was never clicked). */
  initialDetailOpen?: boolean;
}

/** Shared inbox layout for every admin moderation queue (reports today,
 * submissions and the event inspector next — issue #155): a compact row
 * list on the left, a full-context detail panel on the right, no modal.
 * Callers own row/detail content entirely (renderRow/renderDetail) — this
 * component only owns selection, the resolved-row treatment, and the
 * list-then-detail collapse below MOBILE_BREAKPOINT_PX. */
export default function AdminQueueSplitView<T>({
  items,
  getId,
  isResolved,
  resolvedTag,
  selectedId,
  onSelect,
  renderRow,
  renderDetail,
  emptyLabel,
  initialDetailOpen = false,
}: AdminQueueSplitViewProps<T>) {
  const [mobileDetailOpen, setMobileDetailOpen] = useState(initialDetailOpen);

  if (items.length === 0) {
    return <p className={styles.empty}>{emptyLabel}</p>;
  }

  const current = items.find((item) => getId(item) === selectedId) ?? items[0];

  function select(id: number) {
    onSelect(id);
    setMobileDetailOpen(true);
  }

  return (
    <div className={styles.wrap}>
      <div className={`${styles.list} ${mobileDetailOpen ? styles.listHiddenMobile : ''}`}>
        {items.map((item) => {
          const id = getId(item);
          const resolved = isResolved(item);
          return (
            <button
              key={id}
              type="button"
              className={cx(styles.row, id === getId(current) && styles.rowActive, resolved && styles.rowResolved)}
              onClick={() => select(id)}
            >
              {renderRow(item)}
              {resolved && <span className={styles.resolvedTag}>{resolvedTag(item)}</span>}
            </button>
          );
        })}
      </div>
      <div className={`${styles.detail} ${mobileDetailOpen ? styles.detailShownMobile : ''}`}>
        <button type="button" className={styles.backBtn} onClick={() => setMobileDetailOpen(false)}>
          ← Back to list
        </button>
        {renderDetail(current)}
      </div>
    </div>
  );
}
