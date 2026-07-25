import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { StatusCodes } from 'http-status-codes';
import { api, ApiError } from '../../api/client';
import { getLocale } from '../../lib/auth';
import { t } from '../../i18n';
import { UI_STATE, type UnsubscribeState } from '../../constants';
import styles from './Unsubscribe.module.css';

export default function Unsubscribe() {
  const locale = getLocale();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const [state, setState] = useState<UnsubscribeState>(token ? UI_STATE.working : UI_STATE.error);
  const [errorMsg, setErrorMsg] = useState(token ? '' : t('unsubscribe.error', locale));
  const [resubscribePending, setResubscribePending] = useState(false);
  const called = useRef(false);

  useEffect(() => {
    if (!token) return;
    if (called.current) return;
    called.current = true;

    async function run(tok: string) {
      try {
        await api.post(`/email/unsubscribe?token=${encodeURIComponent(tok)}`);
        setState(UI_STATE.success);
      } catch (err) {
        setState(UI_STATE.error);
        setErrorMsg(
          err instanceof ApiError && err.status === StatusCodes.BAD_REQUEST
            ? t('unsubscribe.expired', locale)
            : t('unsubscribe.error', locale)
        );
      }
    }
    void run(token);
  }, [token, locale]);

  async function handleResubscribe() {
    if (!token || resubscribePending) return;
    setResubscribePending(true);
    try {
      await api.post(`/email/resubscribe?token=${encodeURIComponent(token)}`);
      setState(UI_STATE.resubscribed);
    } catch {
      setErrorMsg(t('unsubscribe.error', locale));
    } finally {
      setResubscribePending(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <span className={styles.radar} aria-hidden>◉</span>
        <h1 className={styles.brand}>{t('brand', locale)}</h1>

        {state === UI_STATE.working && (
          <div className={styles.status} role="status" aria-live="polite">
            <span className={styles.spinner} aria-label={t('unsubscribe.working', locale)} />
            <p className={styles.message}>{t('unsubscribe.working', locale)}</p>
          </div>
        )}

        {state === UI_STATE.success && (
          <div className={styles.status} role="status">
            <div className={styles.check}>✓</div>
            <p className={styles.message}>{t('unsubscribe.success', locale)}</p>
            <button
              type="button"
              className={styles.resubscribeBtn}
              onClick={() => void handleResubscribe()}
              disabled={resubscribePending}
            >
              {t('unsubscribe.resubscribe', locale)}
            </button>
          </div>
        )}

        {state === UI_STATE.resubscribed && (
          <div className={styles.status} role="status">
            <div className={styles.check}>✓</div>
            <p className={styles.message}>{t('unsubscribe.resubscribed', locale)}</p>
          </div>
        )}

        {state === UI_STATE.error && (
          <div className={styles.status} role="alert">
            <div className={styles.errorIcon}>✕</div>
            <p className={styles.message}>{errorMsg}</p>
            <a href="/settings" className={styles.settingsLink}>
              {t('unsubscribe.manage_settings', locale)}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
