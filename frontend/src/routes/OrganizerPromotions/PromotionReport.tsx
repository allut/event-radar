import { useQuery } from '@tanstack/react-query';
import { organizerApi } from '../../api/client';
import PageState from '../../components/PageState';
import { API, QUERY_KEYS } from '../../constants/api';
import { UI_STATE } from '../../constants/core';
import { t, ti, tn } from '../../i18n';
import {
  formatPromoDay,
  pauseReasonKey,
  type PromotionReport as PromotionReportData,
} from '../../lib/organizerPromotions';
import { formatCount } from '../../utils';
import styles from './OrganizerPromotions.module.css';

const FOOTNOTE_KEYS = [
  'promo_report_foot_1',
  'promo_report_foot_2',
  'promo_report_foot_3',
  'promo_report_foot_4',
  'promo_report_foot_5',
] as const;

interface PromotionReportProps {
  promotionId: number;
  panelId: string;
  title: string;
  /** Live or paused: the reach figure is still growing. */
  running: boolean;
  locale: string;
}

/** The purchasing Organizer's per-day report (#616): complete days only, with
 * paused days worded in plain words, one Daily 5 reach figure and the honest
 * notes. It carries no viewer data. */
export default function PromotionReport({ promotionId, panelId, title, running, locale }: PromotionReportProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: [QUERY_KEYS.organizerPromotionReport, promotionId],
    queryFn: () => organizerApi.get<PromotionReportData>(API.organizerPromotionReport(promotionId)),
  });

  return (
    <section id={panelId} className={styles.report} aria-label={ti('promo_report_aria', locale, { title })}>
      <div className={styles.repHead}>
        <h3 className={styles.eyebrowSm}>{t('promo_report_title', locale)}</h3>
        <span className={styles.repNote}>{t('promo_report_note', locale)}</span>
      </div>

      {isLoading ? (
        <PageState kind={UI_STATE.loading} message={t('loading', locale)} inline />
      ) : isError || !data ? (
        <PageState kind={UI_STATE.error} message={t('promo_report_error', locale)} inline />
      ) : (
        <>
          {data.days.length === 0 ? (
            <p className={styles.repEmpty}>{t('promo_report_empty', locale)}</p>
          ) : (
            <table className={styles.rtab}>
              <thead>
                <tr>
                  <th scope="col">{t('promo_col_day', locale)}</th>
                  <th scope="col">{t('promo_col_status', locale)}</th>
                  <th scope="col">{t('promo_col_explore', locale)}</th>
                  <th scope="col">{t('promo_col_daily5', locale)}</th>
                  <th scope="col">{t('promo_col_digest', locale)}</th>
                  <th scope="col">{t('promo_col_opens', locale)}</th>
                </tr>
              </thead>
              <tbody>
                {data.days.map((day) => {
                  const counted = day.shown;
                  const figure = (value: number) => (counted ? formatCount(value, locale) : '—');
                  return (
                    <tr key={day.day}>
                      <td data-label={t('promo_col_day', locale)}>{formatPromoDay(day.day, locale)}</td>
                      <td
                        data-label={t('promo_col_status', locale)}
                        className={day.paused ? styles.pausedText : counted ? styles.shownText : undefined}
                      >
                        {day.paused
                          ? ti('promo_day_paused', locale, {
                              reason: t(`promo_why_${pauseReasonKey(day.paused_reason)}_short`, locale),
                            })
                          : counted
                            ? t('promo_day_shown', locale)
                            : '—'}
                      </td>
                      <td className={counted ? undefined : styles.dim} data-label={t('promo_col_explore', locale)}>
                        {figure(day.explore_served)}
                      </td>
                      <td className={counted ? undefined : styles.dim} data-label={t('promo_col_daily5', locale)}>
                        {figure(day.daily5_placed)}
                      </td>
                      <td className={counted ? undefined : styles.dim} data-label={t('promo_col_digest', locale)}>
                        {figure(day.digest_sent)}
                      </td>
                      <td className={counted ? undefined : styles.dim} data-label={t('promo_col_opens', locale)}>
                        {figure(day.web_opens + day.digest_opens)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          {data.daily5_reach !== null && (
            <div className={styles.reachBox}>
              <span className={styles.reachLabel}>
                {t('promo_reach_label', locale)}
                {running && ` · ${t('promo_reach_so_far', locale)}`}
              </span>
              <span className={styles.reachNum}>
                {tn('promo_people', locale, data.daily5_reach, { count: formatCount(data.daily5_reach, locale) })}
              </span>
              <span className={styles.reachSub}>{t('promo_reach_sub', locale)}</span>
            </div>
          )}

          <ul className={styles.honest}>
            {FOOTNOTE_KEYS.map((key) => (
              <li key={key}>{t(key, locale)}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
