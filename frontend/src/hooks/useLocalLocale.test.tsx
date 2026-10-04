import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, renderHook, act } from '@testing-library/react';
import { useLocalLocale } from './useLocalLocale';
import * as auth from '../lib/auth';
import { getStoredLocale, setLocale } from '../lib/auth';
import { makeRouterQueryWrapper } from '../test/utils';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => {
      const real = actual.useNavigate();
      return (...args: Parameters<typeof real>) => {
        mockNavigate(...args);
        return real(...args);
      };
    },
  };
});

vi.mock('../lib/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/auth')>();
  return { ...actual, setLocale: vi.fn(actual.setLocale) };
});
const mockSetLocale = vi.mocked(auth.setLocale);

beforeEach(() => {
  mockNavigate.mockClear();
  mockSetLocale.mockClear();
  localStorage.clear();
});

const PATH = '/organizer/dashboard';

function makeWrapper(initialPath: string) {
  return makeRouterQueryWrapper({
    initialPath,
    routePatterns: [PATH, `/:locale${PATH}`],
    withLocationProbe: true,
  });
}

function probe() {
  return screen.getByTestId('location-probe');
}

describe('useLocalLocale', () => {
  it('bare path with no stored preference resolves Estonian', () => {
    const { wrapper } = makeWrapper(PATH);
    const { result } = renderHook(() => useLocalLocale(), { wrapper });
    expect(result.current[0]).toBe('et');
  });

  it('locale prefix wins over a stored preference', () => {
    setLocale('en');
    const { wrapper } = makeWrapper(`/ru${PATH}`);
    const { result } = renderHook(() => useLocalLocale(), { wrapper });
    expect(result.current[0]).toBe('ru');
  });

  it('et → en navigates to the prefixed path', () => {
    const { wrapper } = makeWrapper(PATH);
    const { result } = renderHook(() => useLocalLocale(), { wrapper });
    act(() => result.current[1]('en'));
    expect(probe()).toHaveTextContent(`/en${PATH}`);
    expect(result.current[0]).toBe('en');
    expect(getStoredLocale()).toBe('en');
  });

  it('en → et lands on the bare path', () => {
    const { wrapper } = makeWrapper(`/en${PATH}`);
    const { result } = renderHook(() => useLocalLocale(), { wrapper });
    act(() => result.current[1]('et'));
    expect(probe()).toHaveTextContent(PATH);
    expect(probe()).not.toHaveTextContent(`/en${PATH}`);
    expect(result.current[0]).toBe('et');
  });

  it('en → ru swaps the prefix', () => {
    const { wrapper } = makeWrapper(`/en${PATH}`);
    const { result } = renderHook(() => useLocalLocale(), { wrapper });
    act(() => result.current[1]('ru'));
    expect(probe()).toHaveTextContent(`/ru${PATH}`);
  });

  it('preserves query string and hash', () => {
    const { wrapper } = makeWrapper(`${PATH}?tab=past#top`);
    const { result } = renderHook(() => useLocalLocale(), { wrapper });
    act(() => result.current[1]('en'));
    expect(probe()).toHaveTextContent(`/en${PATH}?tab=past#top`);
  });

  it('persists before navigating, and navigates with replace', () => {
    const { wrapper } = makeWrapper(PATH);
    const { result } = renderHook(() => useLocalLocale(), { wrapper });
    act(() => result.current[1]('en'));
    expect(mockSetLocale.mock.invocationCallOrder[0]).toBeLessThan(
      mockNavigate.mock.invocationCallOrder[0],
    );
    expect(mockNavigate).toHaveBeenCalledWith(`/en${PATH}`, { replace: true });
  });
});
