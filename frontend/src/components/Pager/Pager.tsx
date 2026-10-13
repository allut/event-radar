// The shared numbered pager (spec #551): ‹ 1 … 4 5 6 … 13 › beside a range
// label such as "73–96 of 300". One component, no audience variant — the
// caller places it and adds any rule through `className`. Every page is a
// router link (no click callback); usePagedQuery owns what a page change
// does. Collapse to first/current/last is a container query on the pager's
// own width (Pager.module.css).
import { Link, useLocation } from 'react-router-dom';
import { PAGE_QUERY_PARAM, PAGER_LIVE_KEY, type PagerLiveNoun } from '../../constants/api';
import { t, ti } from '../../i18n';
import { cx, formatCount } from '../../utils';
import visually from '../shared/Visually.module.css';
import styles from './Pager.module.css';

/** What the live region says after a push/POP page change (usePagedQuery
 * sets it once the new page's data has rendered; null otherwise). */
export interface PagerAnnouncement {
  page: number;
  lastPage: number;
  from: number;
  to: number;
  total: number;
  totalIsLowerBound: boolean;
}

export interface PagerProps {
  page: number;
  lastPage: number;
  offset: number;
  itemCount: number;
  total: number;
  totalIsLowerBound?: boolean;
  /** Params every page link removes (e.g. Admin Reports' `report`). */
  dropOnPageChange?: string[];
  className?: string;
  locale: string;
  announcement?: PagerAnnouncement | null;
  /** The noun the live region uses: "Events …" or "Items …". */
  liveNoun?: PagerLiveNoun;
}

type Slot =
  | { kind: 'page'; n: number; sibling: boolean }
  | { kind: 'gap'; key: string; full: boolean; collapsed: boolean };

// Full form: 1 … p-1 p p+1 … last. The collapsed form (container query)
// keeps 1, p and last; a gap that only exists once the siblings are hidden
// (e.g. "1 … 3" for p=3) is a collapsed-only gap, so the collapsed row never
// shows "1 3" side by side. A page past lastPage (only under holdEmptyPage)
// renders the real pages 1…lastPage plus itself.
function slots(page: number, lastPage: number): Slot[] {
  const shown = Array.from(new Set([1, page - 1, page, page + 1, lastPage]))
    .filter((n) => n >= 1 && (n <= lastPage || n === page))
    .sort((a, b) => a - b);
  const core = new Set([1, page, lastPage]);
  const out: Slot[] = [];
  let prevShown: number | null = null;
  let prevCore: number | null = null;
  for (const n of shown) {
    const isCore = core.has(n);
    const fullGap = prevShown !== null && n - prevShown > 1;
    const coreGap = isCore && prevCore !== null && n - prevCore > 1;
    if (fullGap || coreGap) out.push({ kind: 'gap', key: `gap-${n}`, full: fullGap, collapsed: coreGap });
    out.push({ kind: 'page', n, sibling: !isCore });
    prevShown = n;
    if (isCore) prevCore = n;
  }
  return out;
}

function formatTotal(total: number, lowerBound: boolean, locale: string): string {
  return `${formatCount(total, locale)}${lowerBound ? '+' : ''}`;
}

function RangeLabel({
  offset,
  itemCount,
  total,
  totalIsLowerBound,
  locale,
}: {
  offset: number;
  itemCount: number;
  total: number;
  totalIsLowerBound: boolean;
  locale: string;
}) {
  const totalText = formatTotal(total, totalIsLowerBound, locale);
  if (itemCount === 0) {
    return <p className={styles.range}>{ti('pager_no_items', locale, { total: totalText })}</p>;
  }
  const values: Record<string, string> = {
    from: formatCount(offset + 1, locale),
    to: formatCount(offset + itemCount, locale),
    total: totalText,
  };
  // The numbers are emphasised, so the template is split on its placeholders
  // rather than interpolated through ti().
  const parts = t('pager_range', locale).split(/(\{\w+\})/).filter(Boolean);
  return (
    <p className={styles.range}>
      {parts.map((part) => {
        const name = /^\{(\w+)\}$/.exec(part)?.[1];
        return name !== undefined && name in values ? (
          <strong key={part}>{values[name]}</strong>
        ) : (
          <span key={part}>{part}</span>
        );
      })}
    </p>
  );
}

function announcementText(
  announcement: PagerAnnouncement | null | undefined,
  liveNoun: PagerLiveNoun,
  locale: string,
): string {
  if (!announcement) return '';
  const totalText = formatCount(announcement.total, locale);
  return ti(PAGER_LIVE_KEY[liveNoun], locale, {
    page: formatCount(announcement.page, locale),
    last: formatCount(announcement.lastPage, locale),
    from: formatCount(announcement.from, locale),
    to: formatCount(announcement.to, locale),
    total: announcement.totalIsLowerBound
      ? ti('pager_more_than', locale, { total: totalText })
      : totalText,
  });
}

export default function Pager({
  page,
  lastPage,
  offset,
  itemCount,
  total,
  totalIsLowerBound = false,
  dropOnPageChange = [],
  className,
  locale,
  announcement = null,
  liveNoun = 'events',
}: PagerProps) {
  const location = useLocation();

  const linkTo = (n: number) => {
    const params = new URLSearchParams(location.search);
    for (const name of dropOnPageChange) params.delete(name);
    if (n <= 1) params.delete(PAGE_QUERY_PARAM);
    else params.set(PAGE_QUERY_PARAM, String(n));
    const search = params.toString();
    return { pathname: location.pathname, search: search ? `?${search}` : '' };
  };

  return (
    <div className={cx(styles.pager, className)}>
      {total > 0 && (
        <div className={styles.bar}>
          <RangeLabel
            offset={offset}
            itemCount={itemCount}
            total={total}
            totalIsLowerBound={totalIsLowerBound}
            locale={locale}
          />
          {Math.max(lastPage, page) > 1 && (
            <nav aria-label={t('pager_nav', locale)}>
              <ol className={styles.pages}>
                <li>
                  {page > 1 ? (
                    <Link to={linkTo(page - 1)} className={styles.step}>
                      <span aria-hidden="true">‹</span>
                      <span className={visually.srOnly}>{t('pager_prev', locale)}</span>
                    </Link>
                  ) : (
                    <span className={styles.stepDead} aria-hidden="true">‹</span>
                  )}
                </li>
                {slots(page, lastPage).map((slot) =>
                  slot.kind === 'gap' ? (
                    <li
                      key={slot.key}
                      aria-hidden="true"
                      className={cx(
                        styles.gap,
                        slot.full && !slot.collapsed && styles.gapFullOnly,
                        !slot.full && slot.collapsed && styles.gapCollapsedOnly,
                      )}
                    >
                      …
                    </li>
                  ) : (
                    <li key={slot.n} className={cx(slot.sibling && styles.sibling)}>
                      <Link
                        to={linkTo(slot.n)}
                        className={slot.n === page ? styles.current : styles.pageLink}
                        aria-current={slot.n === page ? 'page' : undefined}
                      >
                        {/* The space sits outside the hidden span so the
                            accessible name reads "Page 4", not "Page4"; it
                            collapses visually (the span is out of flow). */}
                        <span className={visually.srOnly}>{t('pager_page_prefix', locale)}</span>
                        {` ${formatCount(slot.n, locale)}`}
                      </Link>
                    </li>
                  ),
                )}
                <li>
                  {page < lastPage ? (
                    <Link to={linkTo(page + 1)} className={styles.step}>
                      <span aria-hidden="true">›</span>
                      <span className={visually.srOnly}>{t('pager_next', locale)}</span>
                    </Link>
                  ) : (
                    <span className={styles.stepDead} aria-hidden="true">›</span>
                  )}
                </li>
              </ol>
            </nav>
          )}
        </div>
      )}
      <div role="status" aria-live="polite" className={visually.srOnly}>
        {announcementText(announcement, liveNoun, locale)}
      </div>
    </div>
  );
}
