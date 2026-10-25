import { useRef } from 'react';
import { adminApi } from '../../api/client';
import { ADMIN_DEDUP_GROUPS_PAGE_SIZE } from '../../_generated/sharedConstants';
import { ADMIN_LOADING_LABEL } from '../../constants/admin';
import { API, QUERY_KEYS, PAGE_PARAM } from '../../constants/api';
import { LOCALE_EN, UI_STATE } from '../../constants/core';
import { EVENT_STATUS } from '../../constants/prerender';
import { usePagedQuery } from '../../hooks/usePagedQuery';
import PageState from '../../components/PageState';
import EmptyState from '../../components/EmptyState';
import Pager from '../../components/Pager';
import styles from './AdminDedup.module.css';

interface DedupEventSummary {
  id: number;
  title: string;
  starts_at: string;
  venue: string | null;
  status: string;
  url: string | null;
  is_explicit: boolean;
}

interface DedupGroup {
  dedup_group_id: number;
  events: DedupEventSummary[];
}

interface DedupGroupsResponse {
  group_count: number;
  event_count: number;
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  groups: DedupGroup[];
}

// Read-only dedup group review (issue #162), over the existing
// GET /admin/dedup/groups endpoint and its by-group pagination (issue #153),
// paged with the shared numbered pager (spec #551) — the page lives in ?page.
// Desktop-only: below ADMIN_DESKTOP_BREAKPOINT_PX the .desktopGate message
// (AdminDedup.module.css) replaces .real outright, mirroring AdminPipeline.
export default function AdminDedup() {
  const firstGroupRef = useRef<HTMLDivElement>(null);
  const {
    items: groups,
    total,
    isLoading,
    isError,
    isPlaceholderData,
    pagerProps,
  } = usePagedQuery({
    queryKey: [QUERY_KEYS.adminDedupGroups],
    pageSize: ADMIN_DEDUP_GROUPS_PAGE_SIZE,
    fetchPage: ({ limit, offset }) =>
      adminApi.get<DedupGroupsResponse>(
        `${API.adminDedupGroups}?${PAGE_PARAM.limit}=${limit}&${PAGE_PARAM.offset}=${offset}`,
      ),
    select: (data) => ({ items: data.groups, total: data.total, offset: data.offset }),
    // No selection or actions on Dedup: a page change just resets the
    // scroll and moves focus to the new page's first group.
    onPageSettled: () => {
      window.scrollTo({ top: 0, behavior: 'auto' });
      firstGroupRef.current?.focus({ preventScroll: true });
    },
  });

  return (
    <div>
      <div className={styles.head}>
        <p className={styles.eyebrow}>Admin / Ops</p>
        <h1 className={styles.title}>Dedup groups</h1>
      </div>

      <div className={styles.desktopGate}>
        Come back at a desk — the dedup console needs more room than this screen.
      </div>

      <div className={styles.real}>
        {isLoading ? (
          <PageState kind={UI_STATE.loading} message={ADMIN_LOADING_LABEL} inline />
        ) : isError ? (
          <PageState kind={UI_STATE.error} message="Couldn't load dedup groups." inline />
        ) : groups.length === 0 && total > 0 ? (
          // A past-end page about to clamp to the real last page.
          <PageState kind={UI_STATE.loading} message={ADMIN_LOADING_LABEL} inline />
        ) : groups.length === 0 ? (
          <EmptyState admin title="No dedup groups" message="Nothing flagged as a duplicate right now." />
        ) : (
          <div className={styles.groups} aria-busy={isPlaceholderData}>
            {groups.map((group, index) => (
              <div
                key={group.dedup_group_id}
                ref={index === 0 ? firstGroupRef : undefined}
                tabIndex={-1}
                className={styles.group}
                data-testid={`dedup-group-${group.dedup_group_id}`}
              >
                <div className={styles.groupHead}>
                  <span>Group #{group.dedup_group_id}</span>
                  <span>{group.events.length} events</span>
                </div>
                {group.events.map((event) => (
                  <div key={event.id} className={styles.eventRow}>
                    <div className={styles.evMain}>
                      <div className={styles.evTitle}>{event.title}</div>
                      <div className={styles.evMeta}>
                        {event.venue ?? 'No venue'} · {event.starts_at}
                      </div>
                    </div>
                    <div className={styles.badges}>
                      <span className={event.status === EVENT_STATUS.published ? `${styles.badge} ${styles.badgePublished}` : styles.badge}>
                        {event.status}
                      </span>
                      {event.is_explicit && (
                        <span className={`${styles.badge} ${styles.badgeExplicit}`}>explicit</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
        {/* The pager's strings come from shared/i18n even here: docs/frontend.md "Admin Console" */}
        <Pager {...pagerProps} locale={LOCALE_EN} liveNoun="items" className={styles.pager} />
      </div>
    </div>
  );
}
