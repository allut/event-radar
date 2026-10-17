import type { LegalDoc } from './types';

type LegalLoader = () => Promise<{ default: LegalDoc }>;

/** Locale → dynamic-import loader maps. Each import() becomes its own lazy Vite
 * chunk, so long-form legal prose never lands in the main bundle — it is fetched
 * only when a visitor opens /privacy, /terms or /ranking. */
export const LEGAL_LOADERS: Record<'privacy' | 'terms' | 'ranking', Record<string, LegalLoader>> = {
  privacy: {
    en: () => import('./privacy.en'),
    et: () => import('./privacy.et'),
    ru: () => import('./privacy.ru'),
  },
  terms: {
    en: () => import('./terms.en'),
    et: () => import('./terms.et'),
    ru: () => import('./terms.ru'),
  },
  ranking: {
    en: () => import('./ranking.en'),
    et: () => import('./ranking.et'),
    ru: () => import('./ranking.ru'),
  },
};

export type LegalDocId = keyof typeof LEGAL_LOADERS;
