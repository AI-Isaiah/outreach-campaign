import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { QueueItem } from "../types";
import CopyButton from "./CopyButton";

function getActionType(channel: string, stepOrder: number): string {
  if (channel === "linkedin_connect") return "connect";
  if (channel === "linkedin_message") return "message";
  if (channel === "linkedin_engage") return "engage";
  return "message";
}

function getInstructions(channel: string, stepOrder: number): string {
  if (channel === "linkedin_connect")
    return "Send a connection request with the note below. Personalize if their profile suggests a specific angle.";
  if (channel === "linkedin_message" && stepOrder <= 3)
    return "Send this follow-up message. They've accepted your connection.";
  if (channel === "linkedin_engage")
    return "Engage with their recent content (like/comment), then send the insight message.";
  return "Send this LinkedIn message.";
}

export default function QueueLinkedInCard({
  item,
  campaign,
}: {
  item: QueueItem;
  campaign: string;
}) {
  const [done, setDone] = useState(false);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () =>
      api.markLinkedInDone(
        item.contact_id,
        getActionType(item.channel, item.step_order),
        campaign,
      ),
    onSuccess: () => {
      setDone(true);
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  const aum = item.aum_millions
    ? `$${(item.aum_millions / 1000).toFixed(1)}B`
    : "-";

  if (done) {
    return (
      <div className="bg-green-50 border border-green-200 rounded-lg p-5">
        <div className="flex items-center gap-2">
          <span className="text-green-600 text-lg">&#10003;</span>
          <span className="font-medium text-green-800">
            {item.contact_name} &mdash; Done
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
      {/* Header */}
      <div className="bg-blue-50 px-5 py-3 flex items-center justify-between border-b border-blue-100">
        <div>
          <span className="font-semibold text-gray-900">
            {item.contact_name}
          </span>
          <span className="text-gray-500 mx-2">&middot;</span>
          <span className="text-gray-600">{item.company_name}</span>
          <span className="text-gray-400 ml-2 text-sm">AUM {aum}</span>
        </div>
        <span className="text-sm text-blue-600 font-medium">
          Step {item.step_order}/{item.total_steps}
        </span>
      </div>

      <div className="p-5 space-y-4">
        {/* Instructions */}
        <p className="text-sm text-gray-600 bg-gray-50 px-3 py-2 rounded">
          {getInstructions(item.channel, item.step_order)}
        </p>

        {/* Profile links */}
        <div className="flex gap-3">
          {item.linkedin_url && (
            <a
              href={item.linkedin_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 transition-colors"
            >
              Open LinkedIn
            </a>
          )}
          {item.sales_nav_url && (
            <a
              href={item.sales_nav_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 text-white rounded-md text-sm font-medium hover:bg-gray-800 transition-colors"
            >
              Sales Navigator
            </a>
          )}
        </div>

        {/* Message */}
        {item.rendered_message && (
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Message
              </span>
              <CopyButton text={item.rendered_message} />
            </div>
            <textarea
              readOnly
              value={item.rendered_message}
              className="w-full h-32 p-3 border border-gray-200 rounded-md text-sm bg-gray-50 resize-none focus:outline-none"
            />
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="px-4 py-2 bg-green-600 text-white rounded-md text-sm font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
          >
            {mutation.isPending ? "Saving..." : "Mark as Done"}
          </button>
          {mutation.isError && (
            <span className="text-red-500 text-sm self-center">
              {(mutation.error as Error).message}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
