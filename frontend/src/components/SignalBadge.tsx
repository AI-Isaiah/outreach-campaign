import { useState, useRef } from "react";
import type { FundSignal } from "../types";

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1) + "\u2026";
}

function SignalBadge({ signals }: { signals: FundSignal[] }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  if (!signals || signals.length === 0) return null;

  const top = signals[0];

  const handleMouseEnter = () => {
    clearTimeout(timeoutRef.current);
    setShowTooltip(true);
  };

  const handleMouseLeave = () => {
    timeoutRef.current = setTimeout(() => setShowTooltip(false), 150);
  };

  return (
    <span
      className="relative inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-blue-50 text-blue-700 border border-blue-200 cursor-default"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {truncate(top.text, 40)}
      {showTooltip && (
        <span className="absolute left-0 top-full mt-1 z-50 bg-gray-900 text-white px-3 py-2 rounded-lg text-sm max-w-xs shadow-lg whitespace-normal">
          {top.text}
        </span>
      )}
    </span>
  );
}

export default SignalBadge;
