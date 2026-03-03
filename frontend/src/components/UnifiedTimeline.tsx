import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { TimelineEntry } from "../types";

const TYPE_STYLES: Record<string, string> = {
  email_sent: "border-indigo-400 bg-indigo-50",
  email_drafted: "border-indigo-200 bg-indigo-50/50",
  linkedin_connect_done: "border-blue-400 bg-blue-50",
  linkedin_message_done: "border-blue-400 bg-blue-50",
  linkedin_engage_done: "border-blue-400 bg-blue-50",
  linkedin_insight_done: "border-blue-400 bg-blue-50",
  linkedin_final_done: "border-blue-400 bg-blue-50",
  expandi_connected: "border-blue-400 bg-blue-50",
  expandi_message_sent: "border-blue-400 bg-blue-50",
  whatsapp_sent: "border-green-400 bg-green-50",
  whatsapp_received: "border-green-400 bg-green-50",
  replied_positive: "border-emerald-400 bg-emerald-50",
  replied_negative: "border-red-400 bg-red-50",
  neutral: "border-gray-300 bg-gray-50",
  positive: "border-emerald-400 bg-emerald-50",
  negative: "border-red-400 bg-red-50",
  general: "border-gray-300 bg-gray-50",
};

const SOURCE_LABELS: Record<string, string> = {
  event: "Event",
  gmail: "Gmail",
  reply: "Reply",
  whatsapp: "WhatsApp",
  note: "Note",
};

function getStyle(entry: TimelineEntry): string {
  return TYPE_STYLES[entry.interaction_type] || "border-gray-200 bg-white";
}

function formatType(type: string): string {
  return type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function UnifiedTimeline({
  contactId,
}: {
  contactId: number;
}) {
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery({
    queryKey: ["timeline", contactId, page],
    queryFn: () => api.getContactTimeline(contactId, page),
  });

  if (isLoading) return <p className="text-gray-400 text-sm">Loading timeline...</p>;
  if (!data || data.entries.length === 0) {
    return <p className="text-gray-400 text-sm">No interactions yet.</p>;
  }

  return (
    <div className="space-y-3">
      {data.entries.map((entry: TimelineEntry, idx: number) => (
        <div
          key={`${entry.occurred_at}-${idx}`}
          className={`border-l-4 rounded-md p-3 ${getStyle(entry)}`}
        >
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-gray-600 uppercase">
                {SOURCE_LABELS[entry.source] || entry.source}
              </span>
              <span className="text-xs font-medium text-gray-700">
                {formatType(entry.interaction_type)}
              </span>
            </div>
            <span className="text-xs text-gray-400">{entry.occurred_at}</span>
          </div>

          {entry.subject && (
            <div className="text-sm font-medium text-gray-800 mb-1">
              {entry.subject}
            </div>
          )}

          {entry.body && (
            <div className="text-sm text-gray-600 whitespace-pre-wrap line-clamp-4">
              {entry.body}
            </div>
          )}
        </div>
      ))}

      {data.pages > 1 && (
        <div className="flex justify-center pt-2">
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={page >= data.pages}
            className="px-4 py-1.5 text-sm text-blue-600 hover:text-blue-800 disabled:text-gray-300"
          >
            {page < data.pages ? "Load more" : "No more entries"}
          </button>
        </div>
      )}
    </div>
  );
}
