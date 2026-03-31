import { X } from "lucide-react";

export default function KeyboardHint({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-2 text-sm text-blue-700 flex items-center justify-between">
      <span>
        Navigate with{" "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">j</kbd>
        /
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">k</kbd>
        {" \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">Space</kbd>
        {" to select \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">s</kbd>
        {" to skip \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">Ctrl+Enter</kbd>
        {" to review & send"}
      </span>
      <button
        onClick={onDismiss}
        className="text-blue-400 hover:text-blue-600 ml-3 flex-shrink-0"
        aria-label="Dismiss keyboard hints"
      >
        <X size={16} />
      </button>
    </div>
  );
}
