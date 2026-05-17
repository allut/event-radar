// ─── React Query ─────────────────────────────────────────────────────────────
export const QUERY_RETRY = 1;
export const QUERY_STALE_TIME = 30_000;

// ─── Local storage keys ──────────────────────────────────────────────────────
export const TOKEN_KEY = 'session_token';
export const LOCALE_KEY = 'locale';

// ─── Auth / magic link ───────────────────────────────────────────────────────
// Keep in sync with MAGIC_LINK_TTL_MINUTES in backend/app/config.py
export const MAGIC_LINK_EXPIRY_MINUTES = 15;
export const AUTH_REDIRECT_DELAY_MS = 600;

// ─── Animation ───────────────────────────────────────────────────────────────
export const CARD_ANIMATION_DELAY_STEP_MS = 80;

// ─── Settings ────────────────────────────────────────────────────────────────
export const SAVE_MSG_CLEAR_DELAY_MS = 2000;

// ─── Persona weights (frontend thresholds) ───────────────────────────────────
// Keep in sync with PERSONA_PRIMARY_WEIGHT / PERSONA_SECONDARY_WEIGHT in backend/app/constants.py
export const PERSONA_PRIMARY_WEIGHT_THRESHOLD = 1.0;

// ─── Locale ──────────────────────────────────────────────────────────────────
const LOCALE_CODE_MAP: Record<string, string> = {
  et: 'et-EE',
  ru: 'ru-RU',
};
const DEFAULT_LOCALE_CODE = 'en-GB';

export function toLocaleCode(locale: string): string {
  return LOCALE_CODE_MAP[locale] ?? DEFAULT_LOCALE_CODE;
}

export const LOCALES = [
  { code: 'en', label: 'EN' },
  { code: 'et', label: 'ET' },
  { code: 'ru', label: 'RU' },
] as const;

// ─── Personas ─────────────────────────────────────────────────────────────────
export interface PersonaData {
  slug: string;
  emoji: string;
  name: string;
  vibe: string;
}

export const PERSONAS: PersonaData[] = [
  { slug: 'underground_clubber', emoji: '🎛️', name: 'Underground Clubber', vibe: 'Late-night raves, techno, basement bars' },
  { slug: 'networking_pro',      emoji: '💼', name: 'Networking Pro',      vibe: 'Startup events, pitch nights, professional meetups' },
  { slug: 'weekend_hobbyist',    emoji: '🎨', name: 'Weekend Hobbyist',    vibe: 'Workshops, outdoor activities, craft markets' },
  { slug: 'culture_buff',        emoji: '🎭', name: 'Culture Buff',        vibe: 'Museums, theatre, classical concerts, art openings' },
  { slug: 'family_explorer',     emoji: '👨‍👩‍👧', name: 'Family Explorer',     vibe: 'Kid-friendly, nature walks, weekend excursions' },
];

// ─── Events / feedback ───────────────────────────────────────────────────────
export type Signal = 'like' | 'dislike' | 'bookmark';

export const SIGNAL_CONFIG: Record<Signal, { icon: string; label: string }> = {
  like:     { icon: '👍', label: 'Like' },
  dislike:  { icon: '👎', label: 'Dislike' },
  bookmark: { icon: '🔖', label: 'Bookmark' },
};

export const EUR_SYMBOL = '€';
export const FREE_LABEL = 'Free';

export const CATEGORY_GRADIENTS: Record<string, string> = {
  nightlife:   'linear-gradient(135deg, #1a0a1f 0%, #2d1040 100%)',
  music:       'linear-gradient(135deg, #0a1020 0%, #1a2060 100%)',
  arts:        'linear-gradient(135deg, #1a100a 0%, #3d2010 100%)',
  food:        'linear-gradient(135deg, #0f1a0a 0%, #1a3010 100%)',
  sports:      'linear-gradient(135deg, #0a1a0f 0%, #102030 100%)',
  tech:        'linear-gradient(135deg, #0a0f1a 0%, #0a2030 100%)',
  business:    'linear-gradient(135deg, #0f100a 0%, #1f2010 100%)',
  family:      'linear-gradient(135deg, #1a0a10 0%, #2a1020 100%)',
  outdoor:     'linear-gradient(135deg, #0a1510 0%, #103020 100%)',
  wellness:    'linear-gradient(135deg, #100a15 0%, #1a0a2a 100%)',
  education:   'linear-gradient(135deg, #0a100f 0%, #102020 100%)',
  community:   'linear-gradient(135deg, #100f0a 0%, #201a0a 100%)',
};
export const FALLBACK_GRADIENT = 'linear-gradient(135deg, #1a1f2e 0%, #13161e 100%)';

// ─── UI state types ───────────────────────────────────────────────────────────
export type LoginState = 'idle' | 'loading' | 'success' | 'error';
export type VerifyState = 'verifying' | 'success' | 'error';
