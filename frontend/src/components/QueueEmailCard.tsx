import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { QueueItem } from "../types";
import StatusBadge from "./StatusBadge";

export default function QueueEmailCard({
  item,
  campaign,
}: {
  item: QueueItem;
  campaign: string;
}) {
  const [subject, setSubject] = useState(
    item.rendered_email?.subject || "",
  );
  const [bodyText, setBodyText] = useState(
    item.rendered_email?.body_text || "",
  );
  const [draftStatus, setDraftStatus] = useState(
    item.gmail_draft?.status || null,
  );
  const queryClient = useQueryClient();

  const draftMutation = useMutation({
    mutationFn: () =>
      api.createDraft(
        item.contact_id,
        campaign,
        item.template_id!,
        subject,
        bodyText,
      ),
    onSuccess: () => {
      setDraftStatus("drafted");
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  const aum = item.aum_millions
    ? `$${(item.aum_millions / 1000).toFixed(1)}B`
    : "-";

  const draftLabel =
    draftStatus === "drafted"
      ? "Draft Created"
      : draftStatus === "sent"
        ? "Sent"
        : "Ready";

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
      {/* Header */}
      <div className="bg-amber-50 px-5 py-3 flex items-center justify-between border-b border-amber-100">
        <div>
          <span className="font-semibold text-gray-900">
            {item.contact_name}
          </span>
          <span className="text-gray-500 mx-2">&middot;</span>
          <span className="text-gray-600">{item.company_name}</span>
          <span className="text-gray-400 ml-2 text-sm">AUM {aum}</span>
        </div>
        <div className="flex items-center gap-3">
          {draftStatus && <StatusBadge status={draftStatus} />}
          <span className="text-sm text-amber-700 font-medium">
            Step {item.step_order}/{item.total_steps}
          </span>
        </div>
      </div>

      {item.rendered_email ? (
        <div className="p-5 space-y-4">
          {/* To */}
          <div className="text-sm">
            <span className="text-gray-500">To: </span>
            <span className="font-medium">{item.rendered_email.contact_email}</span>
          </div>

          {/* Subject */}
          <div>
            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
              Subject
            </label>
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Body */}
          <div>
            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
              Body
            </label>
            <textarea
              value={bodyText}
              onChange={(e) => setBodyText(e.target.value)}
              className="w-full h-48 p-3 border border-gray-200 rounded-md text-sm resize-y focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            {draftStatus !== "sent" && (
              <button
                onClick={() => draftMutation.mutate()}
                disabled={draftMutation.isPending || draftStatus === "drafted"}
                className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {draftMutation.isPending
                  ? "Creating..."
                  : draftStatus === "drafted"
                    ? "Draft Created"
                    : "Push to Gmail Draft"}
              </button>
            )}
            {draftMutation.isError && (
              <span className="text-red-500 text-sm self-center">
                {(draftMutation.error as Error).message}
              </span>
            )}
          </div>
        </div>
      ) : (
        <div className="p-5 text-sm text-gray-500">
          Could not render email preview. Check contact eligibility.
        </div>
      )}
    </div>
  );
}
