import {
  createContext,
  useCallback,
  useEffect,
  useRef,
  ReactNode,
} from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Context levels ordered by priority. Higher number = higher priority. */
export type ContextLevel = "page" | "panel" | "modal";

const CONTEXT_PRIORITY: Record<ContextLevel, number> = {
  page: 0,
  panel: 1,
  modal: 2,
};

/** Descriptor for a key binding, e.g. "Shift+Enter", "j", "Shift+x". */
type KeyDescriptor = string;

interface ShortcutRegistration {
  /** Parsed key (lowercase, without modifier prefix). */
  key: string;
  /** Whether Shift modifier is required. */
  shift: boolean;
  /** Whether Ctrl/Meta modifier is required. */
  ctrl: boolean;
  /** Whether Alt modifier is required. */
  alt: boolean;
  /** Callback to invoke when the shortcut fires. */
  handler: (e: KeyboardEvent) => void;
  /** Context level this shortcut belongs to. */
  level: ContextLevel;
}

export interface ShortcutContextValue {
  /**
   * Register a keyboard shortcut at a given context level.
   *
   * Key descriptor examples: "j", "Enter", "Shift+Enter", "Shift+x", "Ctrl+s"
   *
   * Returns an unregister function -- call it in your useEffect cleanup.
   */
  registerShortcut: (
    keyDescriptor: KeyDescriptor,
    handler: (e: KeyboardEvent) => void,
    level: ContextLevel,
  ) => () => void;

  /**
   * Push a context level onto the stack.
   * While a higher-priority context is active, lower-level shortcuts are
   * suppressed. Idempotent: pushing the same level twice is a no-op.
   */
  pushContext: (level: ContextLevel) => void;

  /**
   * Pop a context level from the stack.
   * Idempotent: popping a level that isn't active is a no-op.
   */
  popContext: (level: ContextLevel) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Parse a key descriptor like "Shift+Enter" into its components. */
function parseDescriptor(descriptor: KeyDescriptor): {
  key: string;
  shift: boolean;
  ctrl: boolean;
  alt: boolean;
} {
  const parts = descriptor.split("+");
  const modifiers = parts.slice(0, -1).map((m) => m.toLowerCase());
  const key = parts[parts.length - 1];

  return {
    key,
    shift: modifiers.includes("shift"),
    ctrl: modifiers.includes("ctrl") || modifiers.includes("meta"),
    alt: modifiers.includes("alt"),
  };
}

/** Check whether the event target is an editable element. */
function isEditableTarget(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

export const ShortcutContext = createContext<ShortcutContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function ShortcutProvider({ children }: { children: ReactNode }) {
  // All registrations, keyed by a unique id for fast removal.
  const registrationsRef = useRef<Map<number, ShortcutRegistration>>(new Map());
  const nextIdRef = useRef(0);

  // Active context levels as a Set for O(1) lookup.
  const activeContextsRef = useRef<Set<ContextLevel>>(new Set(["page"]));

  // -----------------------------------------------------------------------
  // Core keydown handler (single listener for the entire app)
  // -----------------------------------------------------------------------
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // Suppress all shortcuts when focus is inside an editable element.
    if (isEditableTarget(e.target)) return;

    // Determine the highest active context level.
    let highestPriority = -1;
    for (const level of activeContextsRef.current) {
      const p = CONTEXT_PRIORITY[level];
      if (p > highestPriority) highestPriority = p;
    }

    // Walk registrations and fire matching handlers at the highest level.
    for (const reg of registrationsRef.current.values()) {
      if (CONTEXT_PRIORITY[reg.level] !== highestPriority) continue;

      const keyMatch = e.key === reg.key;
      const shiftMatch = reg.shift === e.shiftKey;
      const ctrlMatch = reg.ctrl === (e.ctrlKey || e.metaKey);
      const altMatch = reg.alt === e.altKey;

      if (keyMatch && shiftMatch && ctrlMatch && altMatch) {
        e.preventDefault();
        reg.handler(e);
        // Don't break -- allow multiple handlers for the same key at the
        // same level (different components may register the same shortcut
        // and the caller is responsible for cleanup).
        return;
      }
    }
  }, []);

  // Attach / detach the single global listener.
  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [handleKeyDown]);

  // -----------------------------------------------------------------------
  // registerShortcut
  // -----------------------------------------------------------------------
  const registerShortcut = useCallback(
    (
      keyDescriptor: KeyDescriptor,
      handler: (e: KeyboardEvent) => void,
      level: ContextLevel,
    ): (() => void) => {
      const parsed = parseDescriptor(keyDescriptor);
      const id = nextIdRef.current++;
      const registration: ShortcutRegistration = {
        key: parsed.key,
        shift: parsed.shift,
        ctrl: parsed.ctrl,
        alt: parsed.alt,
        handler,
        level,
      };
      registrationsRef.current.set(id, registration);

      // Return unregister function.
      return () => {
        registrationsRef.current.delete(id);
      };
    },
    [],
  );

  // -----------------------------------------------------------------------
  // pushContext / popContext (idempotent)
  // -----------------------------------------------------------------------
  const pushContext = useCallback((level: ContextLevel) => {
    activeContextsRef.current.add(level);
  }, []);

  const popContext = useCallback((level: ContextLevel) => {
    // Never remove 'page' — it's the baseline context.
    if (level === "page") return;
    activeContextsRef.current.delete(level);
  }, []);

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------
  return (
    <ShortcutContext.Provider
      value={{ registerShortcut, pushContext, popContext }}
    >
      {children}
    </ShortcutContext.Provider>
  );
}
