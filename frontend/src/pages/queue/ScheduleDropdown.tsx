import { useEffect, useRef, useState } from "react";
import { Calendar, Clock, ChevronDown, Send } from "lucide-react";
import { SCHEDULE_PRESETS } from "../../constants";

interface ScheduleDropdownProps {
  isPending: boolean;
  onSchedule: (value: string) => void;
}

export default function ScheduleDropdown({ isPending, onSchedule }: ScheduleDropdownProps) {
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [customDateTime, setCustomDateTime] = useState("");
  const scheduleRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (scheduleRef.current && !scheduleRef.current.contains(e.target as Node)) {
        setScheduleOpen(false);
      }
    }
    if (scheduleOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [scheduleOpen]);

  return (
    <div className="relative" ref={scheduleRef}>
      <button
        type="button"
        onClick={() => setScheduleOpen((prev) => !prev)}
        disabled={isPending}
        className="inline-flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        <Clock size={16} />
        Schedule
        <ChevronDown size={14} />
      </button>
      {scheduleOpen && (
        <div className="absolute bottom-full right-0 mb-2 w-64 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-50">
          {SCHEDULE_PRESETS.map((preset) => {
            const Icon = preset.value === "now" ? Send : preset.value === "tomorrow_9am" ? Clock : Calendar;
            return (
              <button
                key={preset.value}
                type="button"
                onClick={() => { onSchedule(preset.value); setScheduleOpen(false); setCustomDateTime(""); }}
                className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
              >
                <Icon size={14} className="text-gray-400" />
                {preset.label}
              </button>
            );
          })}
          <div className="border-t border-gray-100 mt-1 pt-1 px-4 py-2">
            <label className="text-xs font-medium text-gray-500 block mb-1.5">
              Custom date & time
            </label>
            <input
              type="datetime-local"
              value={customDateTime}
              onChange={(e) => setCustomDateTime(e.target.value)}
              className="w-full border border-gray-200 rounded px-2.5 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <button
              type="button"
              disabled={!customDateTime}
              onClick={() => { onSchedule(new Date(customDateTime).toISOString()); setScheduleOpen(false); setCustomDateTime(""); }}
              className="mt-2 w-full bg-blue-600 text-white rounded text-sm font-medium px-3 py-1.5 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Schedule for this time
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
