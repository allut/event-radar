import { TOKEN_KEY, LOCALES, LOCALE_KEY } from '../constants';

export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string): void => { localStorage.setItem(TOKEN_KEY, t); };
export const clearToken = (): void => { localStorage.removeItem(TOKEN_KEY); };
export const isAuthenticated = (): boolean => !!getToken();

export const getLocale = (): string => localStorage.getItem(LOCALE_KEY) ?? LOCALES[0].code;
export const setLocale = (l: string): void => { localStorage.setItem(LOCALE_KEY, l); };
