import { useState, useRef, useEffect } from "react";
import { SKIP_REASONS, REMOVE_REASON } from "../utils/queue";

export default function SkipMenu({
  onSkip,
  isPending,
}: {
  onSkip: (reason: string) => void;
  isPending: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        disabled={isPending}
        className="px-2.5 py-1 text-xs text-gray-500 border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50 transition-colors"
        title="Skip this contact"
      >
        {isPending ? "..." : "Skip"}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 w-48 bg-white border border-gray-200 rounded-lg shadow-lg z-10">
          {SKIP_REASONS.filter(r => r !== REMOVE_REASON).map((reason) => (
            <button
              key={reason}
              onClick={() => {
                setOpen(false);
                onSkip(reason);
              }}
              className="block w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 first:rounded-t-lg"
            >
              {reason}
            </button>
          ))}
          <div className="border-t border-gray-100" />
          <button
            onClick={() => {
              if (window.confirm("Remove this contact? They'll be hidden from all lists and queues. You can restore them later if re-uploaded.")) {
                setOpen(false);
                onSkip(REMOVE_REASON);
              }
            }}
            className="block w-full text-left px-3 py-2 text-sm text-red-600 hover:bg-red-50 rounded-b-lg"
          >
            Remove from Contacts
          </button>
        </div>
      )}
    </div>
  );
}
