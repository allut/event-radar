import { memo, useCallback, useState } from 'react';
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

interface QueueRowListProps<T> {
  items: T[];
  getId: (item: T) => number;
  isResolved: (item: T) => boolean;
  resolvedTag: (item: T) => string;
  currentId: number;
  onSelect: (id: number) => void;
  renderRow: (item: T) => React.ReactNode;
  hiddenMobile: boolean;
}

// Split out and memo'd so the row list (up to a full page of items) skips
// re-rendering when only the detail panel's local state changes — e.g. every
// keystroke in a resolution-note textarea (Big-O audit #5, item 3.5). This
// only pays off when callers keep getId/isResolved/resolvedTag/onSelect/
// renderRow referentially stable (useCallback) across those re-renders.
function QueueRowListInner<T>({
  items,
  getId,
  isResolved,
  resolvedTag,
  currentId,
  onSelect,
  renderRow,
  hiddenMobile,
}: QueueRowListProps<T>) {
  return (
    <div className={`${styles.list} ${hiddenMobile ? styles.listHiddenMobile : ''}`}>
      {items.map((item) => {
        const id = getId(item);
        const resolved = isResolved(item);
        return (
          <button
            key={id}
            type="button"
            className={cx(styles.row, id === currentId && styles.rowActive, resolved && styles.rowResolved)}
            onClick={() => onSelect(id)}
          >
            {renderRow(item)}
            {resolved && <span className={styles.resolvedTag}>{resolvedTag(item)}</span>}
          </button>
        );
      })}
    </div>
  );
}
const QueueRowList = memo(QueueRowListInner) as typeof QueueRowListInner;

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

  const select = useCallback(
    (id: number) => {
      onSelect(id);
      setMobileDetailOpen(true);
    },
    [onSelect],
  );

  if (items.length === 0) {
    return <p className={styles.empty}>{emptyLabel}</p>;
  }

  const current = items.find((item) => getId(item) === selectedId) ?? items[0];
  // Hoisted out of the .map below — getId(current) is otherwise recomputed
  // once per row every render (Big-O audit M4).
  const currentId = getId(current);

  return (
    <div className={styles.wrap}>
      <QueueRowList
        items={items}
        getId={getId}
        isResolved={isResolved}
        resolvedTag={resolvedTag}
        currentId={currentId}
        onSelect={select}
        renderRow={renderRow}
        hiddenMobile={mobileDetailOpen}
      />
      <div className={`${styles.detail} ${mobileDetailOpen ? styles.detailShownMobile : ''}`}>
        <button type="button" className={styles.backBtn} onClick={() => setMobileDetailOpen(false)}>
          ← Back to list
        </button>
        {renderDetail(current)}
      </div>
    </div>
  );
}
