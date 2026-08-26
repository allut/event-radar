import { useMemo } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { adminApi } from '../../api/client';
import { API, QUERY_KEYS, UI_STATE, ADMIN_DEDUP_GROUPS_PAGE_SIZE } from '../../constants';
import PageState from '../../components/PageState';
import EmptyState from '../../components/EmptyState';
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
  total_groups: number;
  limit: number;
  offset: number;
  has_more: boolean;
  groups: DedupGroup[];
}

// Read-only dedup group review (issue #162), over the existing
// GET /admin/dedup/groups endpoint and its by-group pagination (issue #153).
// Desktop-only: below ADMIN_DESKTOP_BREAKPOINT_PX the .desktopGate message
// (AdminDedup.module.css) replaces .real outright, mirroring AdminPipeline.
export default function AdminDedup() {
  const {
    data,
    isLoading,
    isError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: [QUERY_KEYS.adminDedupGroups],
    queryFn: ({ pageParam }) =>
      adminApi.get<DedupGroupsResponse>(
        `${API.adminDedupGroups}?limit=${ADMIN_DEDUP_GROUPS_PAGE_SIZE}&offset=${pageParam}`,
      ),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.groups.length : undefined,
  });

  const groups = useMemo(() => data?.pages.flatMap((page) => page.groups) ?? [], [data]);
  const totalGroups = data?.pages[0]?.total_groups ?? 0;

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
          <PageState kind={UI_STATE.loading} message="Loading…" inline />
        ) : isError ? (
          <PageState kind={UI_STATE.error} message="Couldn't load dedup groups." inline />
        ) : groups.length === 0 ? (
          <EmptyState icon="🔍" title="No dedup groups" message="Nothing flagged as a duplicate right now." />
        ) : (
          <>
            <p className={styles.subtitle}>
              {groups.length} of {totalGroups} groups shown
            </p>
            {groups.map((group) => (
              <div key={group.dedup_group_id} className={styles.group} data-testid={`dedup-group-${group.dedup_group_id}`}>
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
                      <span className={event.status === 'published' ? `${styles.badge} ${styles.badgePublished}` : styles.badge}>
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

            {hasNextPage && (
              <button
                type="button"
                className={styles.loadMoreBtn}
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
              >
                Load more
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
