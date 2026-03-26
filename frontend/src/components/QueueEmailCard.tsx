import { useState, useRef } from "react";
import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Mail, Pencil, Sparkles, CheckCircle } from "lucide-react";
import { api } from "../api/client";
import { queueApi } from "../api/queue";
import AiDraftControls from "./AiDraftControls";
import type { QueueItem } from "../types";
import AumTierBadge from "./AumTierBadge";
import SignalBadge from "./SignalBadge";
import StatusBadge from "./StatusBadge";
import ContactEditPanel from "./ContactEditPanel";
import SkipMenu from "./SkipMenu";
import { useContactEdit } from "../hooks/useContactEdit";

function QueueEmailCard({
  item,
  campaign,
  onDeferred,
  isFocused,
  isApproved,
}: {
  item: QueueItem;
  campaign: string;
  onDeferred?: () => void;
  isFocused?: boolean;
  isApproved?: boolean;
}) {
  const [subject, setSubject] = useState(
    item.message_draft?.draft_subject || item.rendered_email?.subject || "",
  );
  const [bodyText, setBodyText] = useState(
    item.message_draft?.draft_text || item.rendered_email?.body_text || "",
  );
  const [draftStatus, setDraftStatus] = useState(
    item.gmail_draft?.status || null,
  );
  const [skipped, setSkipped] = useState(false);
  const subjectRef = useRef<HTMLInputElement>(null);

  const queryClient = useQueryClient();
  const contactEdit = useContactEdit(item);

  const generateMutation = useMutation({
    mutationFn: () =>
      queueApi.generateDraft(item.contact_id, item.campaign_id!, item.step_order),
    onSuccess: (data) => {
      setSubject(data.draft_subject || "");
      setBodyText(data.draft_text);
      queryClient.invalidateQueries({ queryKey: ["queue-all"], refetchType: "none" });
      setTimeout(() => subjectRef.current?.focus(), 100);
    },
  });

  const skipMutation = useMutation({
    mutationFn: (reason: string) =>
      api.deferContact(item.contact_id, campaign, reason),
    onSuccess: () => {
      setSkipped(true);
      queryClient.invalidateQueries({ queryKey: ["queue-all"] });
      queryClient.invalidateQueries({ queryKey: ["defer-stats"] });
      onDeferred?.();
    },
  });

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
      queryClient.invalidateQueries({ queryKey: ["queue-all"] });
    },
  });

  if (skipped) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-5">
        <div className="flex items-center gap-2">
          <span className="text-gray-400 text-lg">&#8594;</span>
          <span className="font-medium text-gray-500">
            {item.contact_name} &mdash; Skipped (back tomorrow)
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`bg-white border rounded-lg shadow-sm overflow-hidden ${
        isFocused ? "ring-2 ring-blue-500 ring-offset-2 border-blue-300" : "border-gray-200"
      }`}
      aria-label={`Email: ${item.contact_name}`}
    >
      <div className="bg-amber-50 px-5 py-3 flex items-center justify-between border-b border-amber-100">
        <div className="flex items-center gap-1.5">
          {isApproved && <CheckCircle size={16} className="text-green-500 flex-shrink-0" />}
          <Mail size={16} className="text-amber-600 flex-shrink-0" />
          <span className="font-semibold text-gray-900">
            {item.contact_name}
          </span>
          <button
            onClick={() => contactEdit.setShowEdit(!contactEdit.showEdit)}
            className="p-0.5 text-gray-400 hover:text-gray-600 transition-colors"
            title="Edit contact details"
            data-role="edit-contact"
          >
            <Pencil size={14} />
          </button>
          <span className="text-gray-500 mx-1">&middot;</span>
          <span className="text-gray-600">
            {item.company_name}
            {item.firm_type && (
              <span className="text-gray-400 text-sm ml-1">({item.firm_type})</span>
            )}
          </span>
          <AumTierBadge tier={item.aum_tier} />
          {item.fund_signals && item.fund_signals.length > 0 && (
            <SignalBadge signals={item.fund_signals} />
          )}
        </div>
        <div className="flex items-center gap-3">
          {draftStatus && <StatusBadge status={draftStatus} />}
          <span className="text-sm text-amber-700 font-medium">
            Step {item.step_order}/{item.total_steps}
          </span>
          <SkipMenu onSkip={(reason) => skipMutation.mutate(reason)} isPending={skipMutation.isPending} />
        </div>
      </div>

      <ContactEditPanel edit={contactEdit} />

      {item.rendered_email || item.message_draft || generateMutation.isSuccess ? (
        <div className="p-5 space-y-4">
          <div className="text-sm">
            <span className="text-gray-500">To: </span>
            <span className="font-medium">{item.rendered_email?.contact_email || item.email}</span>
          </div>

          <AiDraftControls
            hasAiDraft={!!item.message_draft || generateMutation.isSuccess}
            draftMode={item.draft_mode}
            hasResearch={item.has_research}
            generateMutation={generateMutation}
          />

          {item.draft_mode === "ai" && !(item.message_draft || generateMutation.isSuccess) && (
            <div className="flex items-center gap-2 text-sm text-purple-600 italic">
              <Sparkles size={14} />
              Generate AI draft to personalize this message
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
              Subject
            </label>
            <input
              ref={subjectRef}
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

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

          <div className="flex gap-2 pt-1">
            {draftStatus !== "sent" && (
              <button
                onClick={() => draftMutation.mutate()}
                disabled={
                  draftMutation.isPending ||
                  draftStatus === "drafted" ||
                  (item.draft_mode === "ai" && !(item.message_draft || generateMutation.isSuccess))
                }
                className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                title={item.draft_mode === "ai" && !(item.message_draft || generateMutation.isSuccess) ? "Generate AI Draft first" : undefined}
                aria-disabled={item.draft_mode === "ai" && !(item.message_draft || generateMutation.isSuccess)}
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

export default React.memo(QueueEmailCard);
