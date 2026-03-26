import { useState, useRef } from "react";
import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Linkedin, ChevronDown, ChevronUp, Pencil, Sparkles, CheckCircle } from "lucide-react";
import { api } from "../api/client";
import { queueApi } from "../api/queue";
import AiDraftControls from "./AiDraftControls";
import type { QueueItem } from "../types";
import AumTierBadge from "./AumTierBadge";
import CopyButton from "./CopyButton";
import ContactEditPanel from "./ContactEditPanel";
import SkipMenu from "./SkipMenu";
import { useContactEdit } from "../hooks/useContactEdit";

function getActionType(channel: string): string {
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

function QueueLinkedInCard({
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
  const [done, setDone] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const [showMessage, setShowMessage] = useState(true);
  const [messageText, setMessageText] = useState(
    item.message_draft?.draft_text || item.rendered_message || "",
  );
  const messageRef = useRef<HTMLTextAreaElement>(null);

  const queryClient = useQueryClient();
  const contactEdit = useContactEdit(item);

  const generateMutation = useMutation({
    mutationFn: () =>
      queueApi.generateDraft(item.contact_id, item.campaign_id!, item.step_order),
    onSuccess: (data) => {
      setMessageText(data.draft_text);
      setShowMessage(true);
      queryClient.invalidateQueries({ queryKey: ["queue-all"], refetchType: "none" });
      setTimeout(() => messageRef.current?.focus(), 100);
    },
  });

  const hasAiDraft = !!item.message_draft || generateMutation.isSuccess;

  const mutation = useMutation({
    mutationFn: () =>
      api.markLinkedInDone(
        item.contact_id,
        getActionType(item.channel),
        campaign,
      ),
    onSuccess: () => {
      setDone(true);
      queryClient.invalidateQueries({ queryKey: ["queue-all"] });
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
    <div
      className={`bg-white border rounded-lg shadow-sm overflow-hidden ${
        isFocused ? "ring-2 ring-blue-500 ring-offset-2 border-blue-300" : "border-gray-200"
      }`}
      aria-label={`LinkedIn: ${item.contact_name}`}
    >
      <div className="bg-blue-50 px-5 py-3 flex items-center justify-between border-b border-blue-100">
        <div className="flex items-center gap-1.5">
          {isApproved && <CheckCircle size={16} className="text-green-500 flex-shrink-0" />}
          <Linkedin size={16} className="text-blue-600 flex-shrink-0" />
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
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-blue-600 font-medium">
            Step {item.step_order}/{item.total_steps}
          </span>
          <SkipMenu onSkip={(reason) => skipMutation.mutate(reason)} isPending={skipMutation.isPending} />
        </div>
      </div>

      <ContactEditPanel edit={contactEdit} />

      <div className="p-5 space-y-4">
        <p className="text-sm text-gray-600 bg-gray-50 px-3 py-2 rounded">
          {getInstructions(item.channel, item.step_order)}
        </p>

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

        <AiDraftControls
          hasAiDraft={hasAiDraft}
          draftMode={item.draft_mode}
          hasResearch={item.has_research}
          generateMutation={generateMutation}
        />

        {item.draft_mode === "ai" && !hasAiDraft && (
          <div className="flex items-center gap-2 text-sm text-purple-600 italic">
            <Sparkles size={14} />
            Generate AI draft to personalize this message
          </div>
        )}

        {(item.rendered_message || hasAiDraft) && (
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <button
                onClick={() => setShowMessage(!showMessage)}
                aria-expanded={showMessage}
                className="flex items-center gap-1 text-xs font-medium text-gray-500 uppercase tracking-wide hover:text-gray-700 transition-colors"
              >
                Message
                {showMessage ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>
              <CopyButton
                text={messageText}
                variant="primary"
                ariaLabel="Copy message to clipboard"
              />
            </div>
            {showMessage && (
              <textarea
                ref={messageRef}
                value={messageText}
                onChange={(e) => setMessageText(e.target.value)}
                className="w-full h-32 p-3 border border-gray-200 rounded-md text-sm resize-y focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            )}
          </div>
        )}

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

export default React.memo(QueueLinkedInCard);
