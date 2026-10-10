// Guarded localStorage access. Reading or writing localStorage throws a
// SecurityError when site data is blocked (Safari "block all cookies",
// Firefox dom.storage.enabled=false, sandboxed embeds); every boot-path
// module goes through these so a blocked store degrades to "no stored value"
// instead of white-screening the SPA. Kept dependency-free (no utils.ts) so
// lib/auth, lib/theme etc. can import it without an import cycle.
export function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function storageSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage unavailable — the value is simply not persisted.
  }
}

export function storageRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Storage unavailable — nothing to remove.
  }
}
