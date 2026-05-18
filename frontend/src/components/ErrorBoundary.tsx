import { Component, type ReactNode } from 'react';
import { getLocale } from '../lib/auth';
import { t } from '../i18n';
import styles from './ErrorBoundary.module.css';
import { LOCALES } from '../constants';

interface Props { children: ReactNode }
interface State { hasError: boolean }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: object) {
    console.error('[ErrorBoundary]', error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    let locale: string = LOCALES[0].code; // default to first locale
    try { locale = getLocale(); } catch { /* localStorage unavailable */ }
    return (
      <div className={styles.page}>
        <div className={styles.card}>
          <div className={styles.icon} aria-hidden>⚠</div>
          <h1 className={styles.title}>{t('error_boundary_title', locale)}</h1>
          <p className={styles.msg}>{t('error_boundary_msg', locale)}</p>
          <button className={styles.reloadBtn} onClick={() => window.location.reload()}>
            {t('error_boundary_reload', locale)}
          </button>
        </div>
      </div>
    );
  }
}
