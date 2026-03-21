import { useState } from "react";
import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { QueueItem } from "../types";
import AumTierBadge from "./AumTierBadge";
import StatusBadge from "./StatusBadge";

const SKIP_REASONS = [
  "Not relevant now",
  "Bad timing",
  "Need more research",
  "Too junior",
  "Other",
];

function splitName(fullName: string): [string, string] {
  const parts = fullName.trim().split(/\s+/);
  if (parts.length <= 1) return [parts[0] || "", ""];
  return [parts[0], parts.slice(1).join(" ")];
}

function QueueEmailCard({
  item,
  campaign,
  onDeferred,
}: {
  item: QueueItem;
  campaign: string;
  onDeferred?: () => void;
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
  const [showSkipMenu, setShowSkipMenu] = useState(false);
  const [skipped, setSkipped] = useState(false);

  // Inline edit state
  const [showEdit, setShowEdit] = useState(false);
  const [editFirst, setEditFirst] = useState(() => splitName(item.contact_name)[0]);
  const [editLast, setEditLast] = useState(() => splitName(item.contact_name)[1]);
  const [editLinkedIn, setEditLinkedIn] = useState(item.linkedin_url || "");

  const queryClient = useQueryClient();

  const skipMutation = useMutation({
    mutationFn: (reason: string) =>
      api.deferContact(item.contact_id, campaign, reason),
    onSuccess: () => {
      setSkipped(true);
      queryClient.invalidateQueries({ queryKey: ["queue"] });
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
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  const nameMutation = useMutation({
    mutationFn: () => api.updateContactName(item.contact_id, editFirst, editLast),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  const linkedInMutation = useMutation({
    mutationFn: () => api.updateLinkedInUrl(item.contact_id, editLinkedIn),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  const handleSaveEdit = async () => {
    const promises: Promise<any>[] = [];
    const currentName = item.contact_name;
    const newName = `${editFirst} ${editLast}`.trim();
    if (newName !== currentName) {
      promises.push(nameMutation.mutateAsync());
    }
    if (editLinkedIn !== (item.linkedin_url || "")) {
      promises.push(linkedInMutation.mutateAsync());
    }
    if (promises.length > 0) {
      await Promise.all(promises);
    }
    setShowEdit(false);
  };

  const handleCancelEdit = () => {
    setEditFirst(splitName(item.contact_name)[0]);
    setEditLast(splitName(item.contact_name)[1]);
    setEditLinkedIn(item.linkedin_url || "");
    setShowEdit(false);
  };

  const isSaving = nameMutation.isPending || linkedInMutation.isPending;
  const editError = nameMutation.error || linkedInMutation.error;

  const aum = item.aum_millions
    ? `$${(item.aum_millions / 1000).toFixed(1)}B`
    : "-";

  const draftLabel =
    draftStatus === "drafted"
      ? "Draft Created"
      : draftStatus === "sent"
        ? "Sent"
        : "Ready";

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
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
      {/* Header */}
      <div className="bg-amber-50 px-5 py-3 flex items-center justify-between border-b border-amber-100">
        <div className="flex items-center gap-1.5">
          <span className="font-semibold text-gray-900">
            {item.contact_name}
          </span>
          <button
            onClick={() => setShowEdit(!showEdit)}
            className="p-0.5 text-gray-400 hover:text-gray-600 transition-colors"
            title="Edit contact details"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5">
              <path d="M13.488 2.513a1.75 1.75 0 0 0-2.475 0L3.22 10.303a.75.75 0 0 0-.178.311l-.93 3.255a.75.75 0 0 0 .926.926l3.255-.93a.75.75 0 0 0 .311-.178l7.79-7.79a1.75 1.75 0 0 0 0-2.475l-.906-.906zM11.72 3.22a.25.25 0 0 1 .354 0l.906.906a.25.25 0 0 1 0 .354L5.66 11.8l-1.95.557.557-1.95L11.72 3.22z" />
            </svg>
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
          {draftStatus && <StatusBadge status={draftStatus} />}
          <span className="text-sm text-amber-700 font-medium">
            Step {item.step_order}/{item.total_steps}
          </span>
          <div className="relative">
            <button
              onClick={() => setShowSkipMenu(!showSkipMenu)}
              disabled={skipMutation.isPending}
              className="px-2.5 py-1 text-xs text-gray-500 border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50 transition-colors"
              title="Skip this contact"
            >
              {skipMutation.isPending ? "..." : "Skip"}
            </button>
            {showSkipMenu && (
              <div className="absolute right-0 top-full mt-1 w-48 bg-white border border-gray-200 rounded-lg shadow-lg z-10">
                {SKIP_REASONS.map((reason) => (
                  <button
                    key={reason}
                    onClick={() => {
                      setShowSkipMenu(false);
                      skipMutation.mutate(reason);
                    }}
                    className="block w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 first:rounded-t-lg last:rounded-b-lg"
                  >
                    {reason}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Inline edit panel */}
      {showEdit && (
        <div className="px-5 py-3 bg-gray-50 border-b border-gray-200 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                First Name
              </label>
              <input
                type="text"
                value={editFirst}
                onChange={(e) => setEditFirst(e.target.value)}
                className="w-full px-2.5 py-1.5 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
                Last Name
              </label>
              <input
                type="text"
                value={editLast}
                onChange={(e) => setEditLast(e.target.value)}
                className="w-full px-2.5 py-1.5 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
              LinkedIn URL
            </label>
            <input
              type="url"
              value={editLinkedIn}
              onChange={(e) => setEditLinkedIn(e.target.value)}
              placeholder="https://linkedin.com/in/..."
              className="w-full px-2.5 py-1.5 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleSaveEdit}
              disabled={isSaving}
              className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {isSaving ? "Saving..." : "Save"}
            </button>
            <button
              onClick={handleCancelEdit}
              disabled={isSaving}
              className="px-3 py-1.5 bg-white border border-gray-200 text-gray-700 rounded text-sm font-medium hover:bg-gray-50 disabled:opacity-50 transition-colors"
            >
              Cancel
            </button>
            {editError && (
              <span className="text-red-500 text-xs">
                {(editError as Error).message}
              </span>
            )}
          </div>
        </div>
      )}

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

export default React.memo(QueueEmailCard);
