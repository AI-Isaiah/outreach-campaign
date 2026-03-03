import type { TimelineEntry } from "../types";

export default function WhatsAppMessageCard({
  entry,
}: {
  entry: TimelineEntry;
}) {
  const isOutbound = entry.interaction_type === "whatsapp_sent";

  return (
    <div className={`flex ${isOutbound ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${
          isOutbound
            ? "bg-green-100 text-gray-800 rounded-br-none"
            : "bg-white border border-gray-200 text-gray-800 rounded-bl-none"
        }`}
      >
        {entry.body && (
          <p className="whitespace-pre-wrap">{entry.body}</p>
        )}
        <div
          className={`text-xs mt-1 ${
            isOutbound ? "text-green-600" : "text-gray-400"
          }`}
        >
          {entry.occurred_at}
        </div>
      </div>
    </div>
  );
}
