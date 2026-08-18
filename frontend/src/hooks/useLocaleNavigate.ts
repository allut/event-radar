import { useCallback } from 'react';
import { useNavigate, type NavigateOptions } from 'react-router-dom';
import { useLocalePath } from './useLocalePath';

/** `useNavigate()` wrapper that routes string targets through `useLocalePath()`
 * so a programmatic navigation carries the current locale — numeric deltas
 * (e.g. `navigate(-1)`) pass straight through since there's no target path to
 * prefix. See useLocalePath for why the locale is read from the URL. */
export function useLocaleNavigate(): (to: string | number, options?: NavigateOptions) => void {
  const navigate = useNavigate();
  const localePath = useLocalePath();
  return useCallback(
    (to: string | number, options?: NavigateOptions) => {
      if (typeof to === 'number') {
        navigate(to);
        return;
      }
      navigate(localePath(to), options);
    },
    [navigate, localePath],
  );
}
