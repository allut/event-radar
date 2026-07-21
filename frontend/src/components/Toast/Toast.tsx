import styles from './Toast.module.css';

interface ToastProps {
  status: 'success' | 'error';
  message: string;
}

export default function Toast({ status, message }: ToastProps) {
  if (status === 'success') {
    return <div className={styles.toastSuccess} role="status">{message}</div>;
  }
  return <div className={styles.toastError} role="alert">{message}</div>;
}
