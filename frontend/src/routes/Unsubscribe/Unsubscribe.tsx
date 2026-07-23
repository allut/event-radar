import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { StatusCodes } from 'http-status-codes';
import { api, ApiError } from '../../api/client';
import { getLocale } from '../../lib/auth';
import { t } from '../../i18n';
import styles from './Unsubscribe.module.css';

type UnsubscribeState = 'working' | 'success' | 'resubscribed' | 'error';

export default function Unsubscribe() {
  const locale = getLocale();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const [state, setState] = useState<UnsubscribeState>(token ? 'working' : 'error');
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
        setState('success');
      } catch (err) {
        setState('error');
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
      setState('resubscribed');
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

        {state === 'working' && (
          <div className={styles.status} role="status" aria-live="polite">
            <span className={styles.spinner} aria-label={t('unsubscribe.working', locale)} />
            <p className={styles.message}>{t('unsubscribe.working', locale)}</p>
          </div>
        )}

        {state === 'success' && (
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

        {state === 'resubscribed' && (
          <div className={styles.status} role="status">
            <div className={styles.check}>✓</div>
            <p className={styles.message}>{t('unsubscribe.resubscribed', locale)}</p>
          </div>
        )}

        {state === 'error' && (
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
