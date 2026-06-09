import { TOKEN_KEY, LOCALES, LOCALE_KEY } from '../constants';

export function getToken(): string | null { return localStorage.getItem(TOKEN_KEY); }
export function setToken(t: string): void { localStorage.setItem(TOKEN_KEY, t); }
export function clearToken(): void { localStorage.removeItem(TOKEN_KEY); }
export function isAuthenticated(): boolean { return !!getToken(); }

export function getLocale(): string {
  const stored = localStorage.getItem(LOCALE_KEY);
  return LOCALES.some((l) => l.code === stored) ? stored! : LOCALES[0].code;
}
export function setLocale(l: string): void { localStorage.setItem(LOCALE_KEY, l); }
