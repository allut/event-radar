import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useStaticSeoMeta } from './useStaticSeoMeta';
import { t } from '../i18n';
import { makeRouterQueryWrapper } from '../test/utils';

// useSeoMeta itself (buildSeoMeta) is exhaustively covered by useSeoMeta.test.ts;
// this only exercises the thin wrapper's own logic — titleKey/locale -> "title | brand"
// and pathname sourced from useLocation() rather than a caller-supplied path.

function wrapper(path: string) {
  return makeRouterQueryWrapper({ initialPath: path }).wrapper;
}

describe('useStaticSeoMeta', () => {
  it('builds "{pageTitle} | {brand}" from the given titleKey and locale', () => {
    const { result } = renderHook(() => useStaticSeoMeta('contact_title', 'en'), {
      wrapper: wrapper('/settings'),
    });

    expect(result.current.title).toBe(`${t('contact_title', 'en')} | ${t('brand', 'en')}`);
  });

  it('defaults to noindex (static routes are not indexable)', () => {
    const { result } = renderHook(() => useStaticSeoMeta('contact_title', 'et'), {
      wrapper: wrapper('/settings'),
    });

    expect(result.current.metaTags).toEqual([{ name: 'robots', content: 'noindex' }]);
  });

  it('resolves htmlLang from the passed-in locale, not the route path', () => {
    const { result } = renderHook(() => useStaticSeoMeta('contact_title', 'ru'), {
      wrapper: wrapper('/ru/settings'),
    });

    expect(result.current.htmlLang).toBe('ru');
  });
});
