import { useContext } from "react";
import { ShortcutContext } from "../context/ShortcutContext";
import type { ShortcutContextValue } from "../context/ShortcutContext";

export type { ShortcutContextValue };

/**
 * Hook to access the app-global shortcut manager.
 *
 * Must be used within <ShortcutProvider>.
 *
 * Usage:
 *   const { registerShortcut, pushContext, popContext } = useShortcutManager();
 *
 *   // Register a page-level shortcut (returns unregister fn)
 *   useEffect(() => {
 *     const unsub = registerShortcut('j', () => navigateNext(), 'page');
 *     return unsub;
 *   }, [registerShortcut]);
 *
 *   // When a modal opens:
 *   pushContext('modal');   // page + panel shortcuts now suppressed
 *
 *   // When modal closes:
 *   popContext('modal');    // lower-level shortcuts restored
 */
export function useShortcutManager(): ShortcutContextValue {
  const ctx = useContext(ShortcutContext);
  if (!ctx) {
    throw new Error("useShortcutManager must be used within ShortcutProvider");
  }
  return ctx;
}
