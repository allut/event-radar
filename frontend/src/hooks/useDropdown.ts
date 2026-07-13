import { useEffect, useRef, useState } from 'react';

/**
 * Shared open/close + outside-click + Escape + focus behavior for a
 * trigger-button + popover dropdown (FacetMenu, SelectMenu).
 */
export function useDropdown() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!open) return;

    popRef.current?.querySelector<HTMLButtonElement>('button')?.focus();

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') close();
    }
    function handleClickOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [open]);

  return { open, setOpen, rootRef, popRef, triggerRef, close };
}
