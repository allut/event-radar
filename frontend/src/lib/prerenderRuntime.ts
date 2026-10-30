import { PRERENDER_RUNTIME_FLAG } from '../constants/prerender';

/** True only inside scripts/prerender.ts's headless render, which sets the
 * window flag before the app boots. A real visitor never has it. */
export function isPrerenderRender(): boolean {
  return typeof window !== 'undefined' && (window as unknown as Record<string, unknown>)[PRERENDER_RUNTIME_FLAG] === true;
}
