import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { X, Loader2 } from "lucide-react";
import type { QueueItem } from "../types";
import {
  computeQualityIndicator,
  qualityColor,
  qualityDotClass,
  qualityLabel,
  type QualityLevel,
} from "../utils/qualityIndicator";
import { useShortcutManager } from "../hooks/useShortcutManager";
import Button from "./ui/Button";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ReviewGateModalProps {
  items: QueueItem[];
  onConfirm: (selectedIds: number[]) => void;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Truncate a string to `max` chars, appending ellipsis when trimmed. */
function truncate(text: string | null | undefined, max: number): string {
  if (!text) return "\u2014";
  return text.length > max ? text.slice(0, max) + "\u2026" : text;
}


// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ReviewGateModal({
  items,
  onConfirm,
  onClose,
}: ReviewGateModalProps) {
  // -- Shortcut context management ------------------------------------------
  const { pushContext, popContext, registerShortcut } = useShortcutManager();

  useEffect(() => {
    pushContext("modal");
    return () => {
      popContext("modal");
    };
  }, [pushContext, popContext]);

  // -- Quality computation (stable across re-renders) -----------------------
  const qualityMap = useMemo(() => {
    const map = new Map<number, QualityLevel>();
    for (const item of items) {
      map.set(item.contact_id, computeQualityIndicator(item));
    }
    return map;
  }, [items]);

  // -- Local checked state --------------------------------------------------
  const [checkedIds, setCheckedIds] = useState<Set<number>>(() => {
    const initial = new Set<number>();
    for (const item of items) {
      const q = qualityMap.get(item.contact_id);
      // Pre-check green & amber; leave red unchecked.
      if (q !== "red") {
        initial.add(item.contact_id);
      }
    }
    return initial;
  });

  const [sending, setSending] = useState(false);

  // -- Derived counts -------------------------------------------------------
  const counts = useMemo(() => {
    let green = 0;
    let amber = 0;
    let red = 0;
    for (const item of items) {
      const q = qualityMap.get(item.contact_id)!;
      if (q === "green") green++;
      else if (q === "amber") amber++;
      else red++;
    }
    return { green, amber, red };
  }, [items, qualityMap]);

  const checkedCount = checkedIds.size;
  const allChecked = checkedCount === items.length;

  // -- Toggle handlers ------------------------------------------------------
  const toggleItem = useCallback((id: number) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    if (allChecked) {
      setCheckedIds(new Set());
    } else {
      setCheckedIds(new Set(items.map((i) => i.contact_id)));
    }
  }, [allChecked, items]);

  // -- Confirm / close handlers ---------------------------------------------
  const handleConfirm = useCallback(() => {
    if (checkedCount === 0 || sending) return;
    setSending(true);
    onConfirm(Array.from(checkedIds));
  }, [checkedCount, sending, onConfirm, checkedIds]);

  const handleClose = useCallback(() => {
    if (sending) return; // don't close mid-flight
    onClose();
  }, [sending, onClose]);

  // -- Keyboard shortcuts (modal level) -------------------------------------
  useEffect(() => {
    const unsubEnter = registerShortcut("Enter", () => {
      handleConfirm();
    }, "modal");

    const unsubEscape = registerShortcut("Escape", () => {
      handleClose();
    }, "modal");

    return () => {
      unsubEnter();
      unsubEscape();
    };
  }, [registerShortcut, handleConfirm, handleClose]);

  // -- Focus trap -----------------------------------------------------------
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const modal = modalRef.current;
    if (!modal) return;

    function handleTab(e: KeyboardEvent) {
      if (e.key !== "Tab") return;

      const focusable = modal!.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    document.addEventListener("keydown", handleTab);
    return () => document.removeEventListener("keydown", handleTab);
  }, []);

  // Auto-focus modal on mount for immediate keyboard interaction.
  useEffect(() => {
    modalRef.current?.focus();
  }, []);

  // -- Subject line helper --------------------------------------------------
  function subjectFor(item: QueueItem): string {
    if (item.message_draft?.draft_subject) return item.message_draft.draft_subject;
    if (item.rendered_email?.subject) return item.rendered_email.subject;
    return "\u2014";
  }

  // -- Render ---------------------------------------------------------------
  return (
    /* Overlay */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={handleClose}
      aria-hidden="true"
    >
      {/* Modal dialog */}
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-gate-title"
        tabIndex={-1}
        className="bg-white rounded-xl shadow-2xl w-full max-w-2xl mx-4 flex flex-col outline-none max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ---- Header ---- */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2
            id="review-gate-title"
            className="text-lg font-semibold text-gray-900"
          >
            Review &amp; Send
          </h2>
          <button
            type="button"
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-600 transition-colors rounded-lg p-1 focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>

        {/* ---- Summary bar ---- */}
        <div
          className="flex items-center gap-3 px-6 py-3 bg-gray-50 border-b border-gray-100"
          aria-live="polite"
        >
          <span className="text-sm text-gray-500 font-medium">
            {items.length} item{items.length !== 1 ? "s" : ""}
          </span>
          <span className="text-gray-300">|</span>
          {counts.green > 0 && (
            <span className="bg-green-100 text-green-700 rounded-full px-2 py-0.5 text-xs font-medium">
              {counts.green} ready
            </span>
          )}
          {counts.amber > 0 && (
            <span className="bg-yellow-100 text-yellow-700 rounded-full px-2 py-0.5 text-xs font-medium">
              {counts.amber} template
            </span>
          )}
          {counts.red > 0 && (
            <span className="bg-red-100 text-red-700 rounded-full px-2 py-0.5 text-xs font-medium">
              {counts.red} missing
            </span>
          )}
          <span className="text-gray-300">|</span>
          <span className="text-sm text-gray-600 font-medium">
            {checkedCount} selected
          </span>
        </div>

        {/* ---- Scrollable table ---- */}
        <div className="max-h-[60vh] overflow-y-auto">
          <table className="w-full text-left">
            <thead className="bg-gray-50 border-b border-gray-200 sticky top-0">
              <tr>
                <th className="px-5 py-3 w-10">
                  <input
                    type="checkbox"
                    checked={allChecked}
                    onChange={toggleAll}
                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                    aria-label="Select all items"
                  />
                </th>
                <th className="px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Contact
                </th>
                <th className="px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Company
                </th>
                <th className="px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Subject
                </th>
                <th className="px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide text-center w-20">
                  Quality
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((item) => {
                const quality = qualityMap.get(item.contact_id)!;
                const isChecked = checkedIds.has(item.contact_id);
                return (
                  <tr
                    key={item.contact_id}
                    className={[
                      "hover:bg-gray-50 transition-colors cursor-pointer",
                      isChecked ? "" : "opacity-60",
                    ].join(" ")}
                    onClick={() => toggleItem(item.contact_id)}
                  >
                    <td className="px-5 py-4">
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => toggleItem(item.contact_id)}
                        onClick={(e) => e.stopPropagation()}
                        className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                        aria-label={`Select ${item.contact_name}`}
                      />
                    </td>
                    <td className="px-5 py-4">
                      <span className="text-sm font-medium text-gray-900">
                        {item.contact_name}
                      </span>
                    </td>
                    <td className="px-5 py-4">
                      <span className="text-sm text-gray-600">
                        {item.company_name}
                      </span>
                    </td>
                    <td className="px-5 py-4">
                      {(() => {
                        const subject = subjectFor(item);
                        return (
                          <span
                            className="text-sm text-gray-500 block max-w-[200px] truncate"
                            title={subject}
                          >
                            {truncate(subject, 40)}
                          </span>
                        );
                      })()}
                    </td>
                    <td className="px-5 py-4 text-center">
                      <span
                        className="inline-flex items-center gap-1.5"
                        title={qualityLabel(quality)}
                      >
                        <span
                          className={`inline-block w-2.5 h-2.5 rounded-full ${qualityDotClass(quality)}`}
                          aria-hidden="true"
                        />
                        <span
                          className={`text-xs font-medium rounded-full px-1.5 py-0.5 ${qualityColor(quality)}`}
                        >
                          {quality === "green"
                            ? "Ready"
                            : quality === "amber"
                              ? "Template"
                              : "None"}
                        </span>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* ---- Footer ---- */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200 bg-white rounded-b-xl">
          <Button
            variant="secondary"
            size="md"
            onClick={handleClose}
            disabled={sending}
          >
            Go Back
          </Button>
          <Button
            variant="accent"
            size="md"
            onClick={handleConfirm}
            disabled={checkedCount === 0 || sending}
            loading={sending}
          >
            {sending ? "Sending\u2026" : `Send ${checkedCount}`}
          </Button>
        </div>
      </div>
    </div>
  );
}
