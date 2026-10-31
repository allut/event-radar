import { useId } from 'react';
import { Link } from 'react-router-dom';
import { organizerApi } from '../../api/client';
import { useOrganizerLogout } from '../../hooks/useOrganizerLogout';
import { useLocalLocale } from '../../hooks/useLocalLocale';
import { useLocalePath } from '../../hooks/useLocalePath';
import { usePagedQuery } from '../../hooks/usePagedQuery';
import { usePageSettledFocus } from '../../hooks/usePageSettledFocus';
import { useStaticSeoMeta } from '../../hooks/useStaticSeoMeta';
import { t } from '../../i18n';
import { withLocaleQuery, withQueryParam } from '../../utils/url';
import OrganizerTopBar from '../../components/OrganizerTopBar';
import PageState from '../../components/PageState';
import EmptyState from '../../components/EmptyState';
import Pager from '../../components/Pager';
import SeoTags from '../../components/SeoTags';
import {
  CLAIM_KIND_PUBLISHER,
  CLAIM_STATUS_APPROVED,
  ORGANIZER_OWN_CLAIMS_PAGE_SIZE,
} from '../../_generated/sharedConstants';
import { API, PAGE_PARAM, QUERY_KEYS } from '../../constants/api';
import { type ClaimKind, type ClaimStatus } from '../../constants/claims';
import { UI_STATE } from '../../constants/core';
import { ROUTES } from '../../constants/routes';
import styles from './OrganizerClaims.module.css';

interface OwnClaim {
  id: number;
  kind: ClaimKind;
  status: ClaimStatus;
  verification_mechanism: string | null;
  dormant: boolean;
  publisher_name: string | null;
  event_id: number | null;
  event_title: string | null;
  created_at: string;
  resolved_at: string | null;
}

interface OwnClaimsResponse {
  claims: OwnClaim[];
  total: number;
  pending_count: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

/** Your claims (spec #551): every claim the organizer has made, paged at
 * ORGANIZER_OWN_CLAIMS_PAGE_SIZE with the shared numbered pager. It moved
 * off the dashboard, which keeps only a summary line linking here. */
export default function OrganizerClaims() {
  const [locale, handleLocaleChange] = useLocalLocale();
  const localePath = useLocalePath();
  const handleLogout = useOrganizerLogout();
  const seoMeta = useStaticSeoMeta('dashboard_claims_title', locale);

  // A page change lands on the "Your claims" heading, which sits directly
  // above the list.
  const headingId = useId();
  const { resultsHeadingRef, onPageSettled } = usePageSettledFocus();
  const {
    items: claims,
    total,
    isLoading,
    isError,
    isPlaceholderData,
    pagerProps,
  } = usePagedQuery({
    queryKey: [QUERY_KEYS.organizerClaims, locale],
    pageSize: ORGANIZER_OWN_CLAIMS_PAGE_SIZE,
    fetchPage: ({ limit, offset }) =>
      organizerApi.get<OwnClaimsResponse>(
        withLocaleQuery(
          withQueryParam(
            withQueryParam(API.organizerClaims, PAGE_PARAM.limit, String(limit)),
            PAGE_PARAM.offset,
            String(offset),
          ),
          locale,
        ),
      ),
    select: (data) => ({ items: data.claims, total: data.total, offset: data.offset }),
    onPageSettled,
  });

  return (
    <div className={styles.page}>
      <SeoTags meta={seoMeta} />
      <OrganizerTopBar locale={locale} onLocaleChange={handleLocaleChange} onLogout={handleLogout} />

      <main className={styles.main}>
        <header className={styles.masthead}>
          <h1 id={headingId} ref={resultsHeadingRef} tabIndex={-1} className={styles.heading}>
            {t('dashboard_claims_title', locale)}
          </h1>
          <p className={styles.sub}>{t('dashboard_claims_sub', locale)}</p>
        </header>

        {isLoading ? (
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        ) : isError ? (
          <PageState kind={UI_STATE.error} message={t('generic_error', locale)} inline />
        ) : claims.length === 0 && total > 0 ? (
          // A past-end page about to clamp to the real last page.
          <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
        ) : claims.length === 0 ? (
          <EmptyState
            title={t('organizer_claims_empty_title', locale)}
            message={t('organizer_claims_empty_msg', locale)}
          />
        ) : (
          <ul className={styles.claimsList} aria-labelledby={headingId} aria-busy={isPlaceholderData}>
            {claims.map((claim) => (
              <li key={claim.id} className={styles.claimRow}>
                <div className={styles.claimRowMain}>
                  <span className={styles.rowTitle}>
                    {claim.event_title ?? claim.publisher_name ?? t(`dashboard_claims_kind_${claim.kind}`, locale)}
                  </span>
                  <span className={styles.rowMeta}>
                    {t(`dashboard_claims_kind_${claim.kind}`, locale)}
                  </span>
                </div>
                <div className={styles.claimRowBadges}>
                  <span className={`${styles.claimStatusBadge} ${styles[`claimStatus_${claim.status}`] ?? ''}`}>
                    {t(`dashboard_claims_status_${claim.status}`, locale)}
                  </span>
                </div>
                <div className={styles.claimRowActions}>
                  {claim.status === CLAIM_STATUS_APPROVED && !claim.dormant ? (
                    <>
                      <Link to={localePath(ROUTES.organizerClaimEdit(claim.id))} className={styles.actionBtn}>
                        {t('claim_edit_open_cta', locale)}
                      </Link>
                      {claim.kind === CLAIM_KIND_PUBLISHER && (
                        <Link to={localePath(ROUTES.organizerClaimEvents(claim.id))} className={styles.actionBtn}>
                          {t('claim_events_view_cta', locale)}
                        </Link>
                      )}
                    </>
                  ) : (
                    <Link to={localePath(ROUTES.organizerClaimPending(claim.id))} className={styles.actionBtn}>
                      {t('dashboard_claims_view_status_cta', locale)}
                    </Link>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        <Pager {...pagerProps} locale={locale} className={styles.pager} />
      </main>
    </div>
  );
}
