import { PERSONAS_EN, type PersonaData } from './_generated/i18nData';
import {
  LOCALE_CODE_MAP as _LOCALE_CODE_MAP,
  DEFAULT_LOCALE_CODE as _DEFAULT_LOCALE_CODE,
  LOCALES,
  MAGIC_LINK_EXPIRY_MINUTES,
  PERSONA_PRIMARY_WEIGHT_THRESHOLD,
} from './_generated/sharedConstants';

export { LOCALES, MAGIC_LINK_EXPIRY_MINUTES, PERSONA_PRIMARY_WEIGHT_THRESHOLD };
export type { PersonaData };

// Re-export PERSONAS under the original name so all import sites are unchanged.
export const PERSONAS: PersonaData[] = PERSONAS_EN;

// ─── React Query ─────────────────────────────────────────────────────────────
export const QUERY_RETRY = 1;
export const QUERY_STALE_TIME = 30_000;

// ─── Local storage keys ──────────────────────────────────────────────────────
export const TOKEN_KEY = 'session_token';
export const LOCALE_KEY = 'locale';

// ─── Auth / magic link ───────────────────────────────────────────────────────
export const AUTH_REDIRECT_DELAY_MS = 600;

// ─── Animation ───────────────────────────────────────────────────────────────
export const CARD_ANIMATION_DELAY_STEP_MS = 80;

// ─── Settings ────────────────────────────────────────────────────────────────
export const SAVE_MSG_CLEAR_DELAY_MS = 2000;

// ─── Locale ──────────────────────────────────────────────────────────────────
export function toLocaleCode(locale: string): string {
  return _LOCALE_CODE_MAP[locale] ?? _DEFAULT_LOCALE_CODE;
}

// ─── Events / feedback ───────────────────────────────────────────────────────
export type Signal = 'like' | 'dislike' | 'bookmark';

export const SIGNAL_CONFIG: Record<Signal, { icon: string; label: string }> = {
  like:     { icon: '👍', label: 'Like' },
  dislike:  { icon: '👎', label: 'Dislike' },
  bookmark: { icon: '🔖', label: 'Bookmark' },
};

export const EUR_SYMBOL = '€';
export const FREE_LABEL = 'Free';

// Keys must match the 12-category taxonomy in backend/app/llm/taxonomy.py
export const CATEGORY_GRADIENTS: Record<string, string> = {
  nightlife:    'linear-gradient(135deg, #1a0a1f 0%, #2d1040 100%)',
  music:        'linear-gradient(135deg, #0a1020 0%, #1a2060 100%)',
  theater:      'linear-gradient(135deg, #1a100a 0%, #3d2010 100%)',
  exhibitions:  'linear-gradient(135deg, #100a15 0%, #1a0a2a 100%)',
  workshops:    'linear-gradient(135deg, #0a100f 0%, #102020 100%)',
  food_drink:   'linear-gradient(135deg, #0f1a0a 0%, #1a3010 100%)',
  sports:       'linear-gradient(135deg, #0a1a0f 0%, #102030 100%)',
  networking:   'linear-gradient(135deg, #0a0f1a 0%, #0a2030 100%)',
  literature:   'linear-gradient(135deg, #0f100a 0%, #1f2010 100%)',
  family:       'linear-gradient(135deg, #1a0a10 0%, #2a1020 100%)',
  cinema:       'linear-gradient(135deg, #0a1510 0%, #103020 100%)',
  alternative:  'linear-gradient(135deg, #100f0a 0%, #201a0a 100%)',
};
export const FALLBACK_GRADIENT = 'linear-gradient(135deg, #1a1f2e 0%, #13161e 100%)';

// ─── UI state types ───────────────────────────────────────────────────────────
export type LoginState = 'idle' | 'loading' | 'success' | 'error';
export type VerifyState = 'verifying' | 'success' | 'error';
