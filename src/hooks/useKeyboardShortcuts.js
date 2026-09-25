import { useEffect } from 'react';

export function useKeyboardShortcuts(shortcuts) {
  useEffect(() => {
    const handler = (e) => {
      const key = e.key.toLowerCase();
      const mod = e.metaKey || e.ctrlKey;

      for (const shortcut of shortcuts) {
        const matchKey = shortcut.key.toLowerCase() === key;
        const matchMod = shortcut.mod ? mod : !mod;
        const matchShift = shortcut.shift ? e.shiftKey : !e.shiftKey;

        if (matchKey && matchMod && matchShift) {
          if (shortcut.preventDefault !== false) e.preventDefault();
          shortcut.action(e);
          break;
        }
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [shortcuts]);
}
