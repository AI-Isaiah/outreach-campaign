import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Calendar, CheckCircle, ChevronDown, Clock, Inbox, Mail, Linkedin, Send, X } from "lucide-react";
import { queueApi } from "../api/queue";
import { SCHEDULE_PRESETS } from "../constants";
import { api } from "../api/client";
import type { QueueItem, QueueResponse } from "../types";
import QueueEmailCard from "../components/QueueEmailCard";
import QueueLinkedInCard from "../components/QueueLinkedInCard";
import { SkeletonCard } from "../components/Skeleton";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";

const HINT_STORAGE_KEY = "queue_keyboard_hint_seen_count";
const MAX_HINT_VIEWS = 3;

function KeyboardHint({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-2 text-sm text-blue-700 flex items-center justify-between">
      <span>
        Navigate with{" "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">j</kbd>
        /
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">k</kbd>
        {" \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">Enter</kbd>
        {" to approve \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">s</kbd>
        {" to skip \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">e</kbd>
        {" to edit \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">Tab</kbd>
        {" to switch sections"}
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

type ChannelFilter = "all" | "email" | "linkedin";

export default function Queue() {
  const [channelFilter, setChannelFilter] = useState<ChannelFilter>("all");
  const [campaignFilter, setCampaignFilter] = useState<string>("");
  const [focusedIndex, setFocusedIndex] = useState(0);
  const [approvedIds, setApprovedIds] = useState<Set<number>>(new Set());
  const [showHint, setShowHint] = useState(() => {
    const count = parseInt(localStorage.getItem(HINT_STORAGE_KEY) || "0", 10);
    return count < MAX_HINT_VIEWS;
  });
  const cardRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const queryClient = useQueryClient();

  const { data, isLoading, isError, error, refetch } = useQuery<QueueResponse>({
    queryKey: ["queue-all"],
    queryFn: () => queueApi.getAllQueues({ limit: 50 }),
  });

  const batchDraft = useMutation({
    mutationFn: () => api.createBatchDrafts(campaignFilter),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue-all"] }),
  });

  const skipMutation = useMutation({
    mutationFn: ({ contactId, campaign }: { contactId: number; campaign: string }) =>
      queueApi.deferContact(contactId, campaign, "skipped_via_keyboard"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-all"] });
      queryClient.invalidateQueries({ queryKey: ["defer-stats"] });
    },
  });

  const approveMutation = useMutation({
    mutationFn: (items: { contact_id: number; campaign_id: number }[]) =>
      queueApi.batchApprove(items),
  });

  const [sendProgress, setSendProgress] = useState<string | null>(null);
  const [sendResult, setSendResult] = useState<{ sent: number; failed: number; errors: { contact_id: number; campaign_id: number; error: string }[] } | null>(null);

  const sendMutation = useMutation({
    mutationFn: () => {
      setSendProgress(`Sending ${approvedIds.size} item${approvedIds.size !== 1 ? "s" : ""}...`);
      return queueApi.batchSend();
    },
    onSuccess: (result) => {
      setSendProgress(null);
      setSendResult(result);
      setApprovedIds(new Set());
      queryClient.invalidateQueries({ queryKey: ["queue-all"] });
      setTimeout(() => setSendResult(null), 8000);
    },
    onError: () => {
      setSendProgress(null);
    },
  });

  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [customDateTime, setCustomDateTime] = useState("");
  const scheduleRef = useRef<HTMLDivElement>(null);

  const scheduleMutation = useMutation({
    mutationFn: (schedule: string) => {
      const approvedItems = flatItems
        .filter((i) => approvedIds.has(i.contact_id) && i.campaign_id)
        .map((i) => ({ contact_id: i.contact_id, campaign_id: i.campaign_id! }));
      return queueApi.scheduleSend(approvedItems, schedule);
    },
    onSuccess: (result) => {
      setApprovedIds(new Set());
      setScheduleOpen(false);
      setCustomDateTime("");
      setSendResult({ sent: result.scheduled, failed: 0, errors: [] });
      queryClient.invalidateQueries({ queryKey: ["queue-all"] });
      setTimeout(() => setSendResult(null), 8000);
    },
  });

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

  const allItems: QueueItem[] = data?.items || [];

  // Apply filters
  let items = allItems;
  if (channelFilter === "email") {
    items = items.filter((i) => i.channel === "email");
  } else if (channelFilter === "linkedin") {
    items = items.filter((i) => i.channel.startsWith("linkedin"));
  }
  if (campaignFilter) {
    items = items.filter((i) => i.campaign_name === campaignFilter);
  }

  const emailItems = items.filter((i) => i.channel === "email");
  const linkedinItems = items.filter((i) => i.channel.startsWith("linkedin"));

  const flatItems = useMemo(
    () => [...emailItems, ...linkedinItems],
    [items]
  );

  const handleDeferred = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["queue-all"] }),
    [queryClient],
  );

  // Get unique campaign names from items
  const campaignNames = [...new Set(allItems.map((i) => i.campaign_name).filter((n): n is string => !!n))];

  useEffect(() => {
    if (flatItems.length > 0 && focusedIndex >= flatItems.length) {
      setFocusedIndex(flatItems.length - 1);
    }
  }, [flatItems.length, focusedIndex]);

  // Increment hint view count on mount
  useEffect(() => {
    const count = parseInt(localStorage.getItem(HINT_STORAGE_KEY) || "0", 10);
    if (count < MAX_HINT_VIEWS) {
      localStorage.setItem(HINT_STORAGE_KEY, String(count + 1));
    }
  }, []);

  // Scroll focused card into view
  useEffect(() => {
    if (flatItems.length === 0) return;
    const idx = Math.min(focusedIndex, flatItems.length - 1);
    const el = cardRefs.current.get(idx);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [focusedIndex, flatItems.length]);

  // Keyboard event handler
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable
      ) {
        return;
      }

      if (flatItems.length === 0) return;

      const maxIndex = flatItems.length - 1;

      switch (e.key) {
        case "j": {
          e.preventDefault();
          setFocusedIndex((prev) => Math.min(prev + 1, maxIndex));
          break;
        }
        case "k": {
          e.preventDefault();
          setFocusedIndex((prev) => Math.max(prev - 1, 0));
          break;
        }
        case "Enter": {
          e.preventDefault();
          const idx = Math.min(focusedIndex, maxIndex);
          const item = flatItems[idx];
          if (item && item.campaign_id) {
            const wasApproved = approvedIds.has(item.contact_id);
            setApprovedIds((prev) => {
              const next = new Set(prev);
              if (next.has(item.contact_id)) {
                next.delete(item.contact_id);
              } else {
                next.add(item.contact_id);
              }
              return next;
            });
            if (!wasApproved) {
              approveMutation.mutate([{ contact_id: item.contact_id, campaign_id: item.campaign_id }]);
            }
          }
          break;
        }
        case "s": {
          e.preventDefault();
          const idx = Math.min(focusedIndex, maxIndex);
          const item = flatItems[idx];
          if (item && item.campaign_name) {
            skipMutation.mutate({ contactId: item.contact_id, campaign: item.campaign_name });
          }
          break;
        }
        case "e": {
          e.preventDefault();
          const idx = Math.min(focusedIndex, maxIndex);
          const el = cardRefs.current.get(idx);
          if (el) {
            const editBtn = el.querySelector<HTMLButtonElement>('button[data-role="edit-contact"]');
            if (editBtn) editBtn.click();
          }
          break;
        }
        case "Tab": {
          if (emailItems.length > 0 && linkedinItems.length > 0) {
            e.preventDefault();
            const idx = Math.min(focusedIndex, maxIndex);
            if (idx < emailItems.length) {
              setFocusedIndex(emailItems.length);
            } else {
              setFocusedIndex(0);
            }
          }
          break;
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [flatItems, focusedIndex, emailItems.length, linkedinItems.length, skipMutation, approveMutation, approvedIds]);

  const dismissHint = useCallback(() => {
    setShowHint(false);
    localStorage.setItem(HINT_STORAGE_KEY, String(MAX_HINT_VIEWS));
  }, []);

  const setCardRef = useCallback((index: number, el: HTMLDivElement | null) => {
    if (el) {
      cardRefs.current.set(index, el);
    } else {
      cardRefs.current.delete(index);
    }
  }, []);

  const hasApprovals = approvedIds.size > 0;

  return (
    <div className={`space-y-6 ${hasApprovals ? "pb-20" : ""}`} role="application" aria-label="Outreach queue">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Today's Queue</h1>
          <p className="text-sm text-gray-500 mt-1">
            {allItems.length} action{allItems.length !== 1 ? "s" : ""} across {campaignNames.length} campaign{campaignNames.length !== 1 ? "s" : ""}
            {emailItems.length > 0 && ` \u00b7 ${emailItems.length} email`}
            {linkedinItems.length > 0 && ` \u00b7 ${linkedinItems.length} LinkedIn`}
          </p>
        </div>
        {emailItems.length > 0 && (
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="md"
              onClick={() => batchDraft.mutate()}
              loading={batchDraft.isPending}
              disabled={!campaignFilter && campaignNames.length > 1}
              leftIcon={<CheckCircle size={16} />}
              title={!campaignFilter && campaignNames.length > 1 ? "Filter to a single campaign first" : undefined}
            >
              Create All Drafts
            </Button>
            {batchDraft.isError && (
              <span className="text-red-500 text-sm">
                {(batchDraft.error as Error).message}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="flex gap-2 flex-wrap">
        {(["all", "email", "linkedin"] as ChannelFilter[]).map((f) => (
          <button
            key={f}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              channelFilter === f
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
            onClick={() => setChannelFilter(f)}
          >
            {f === "all" ? "All channels" : f === "email" ? "Email" : "LinkedIn"}
          </button>
        ))}

        {campaignNames.length > 1 && (
          <>
            <div className="w-px bg-gray-200 mx-1" />
            <button
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                !campaignFilter ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
              onClick={() => setCampaignFilter("")}
            >
              All campaigns
            </button>
            {campaignNames.map((cn) => (
              <button
                key={cn}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  campaignFilter === cn
                    ? "bg-gray-900 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
                onClick={() => setCampaignFilter(cn)}
              >
                {cn}
              </button>
            ))}
          </>
        )}
      </div>

      {showHint && flatItems.length > 0 && <KeyboardHint onDismiss={dismissHint} />}

      {isLoading && (
        <div className="space-y-4">
          <SkeletonCard /><SkeletonCard /><SkeletonCard />
        </div>
      )}

      {isError && (
        <ErrorCard message={(error as Error).message} onRetry={() => refetch()} />
      )}

      {!isLoading && !isError && items.length === 0 && (
        <div className="text-center py-16">
          <div className="w-16 h-16 rounded-full bg-green-50 flex items-center justify-center mx-auto mb-4">
            <Inbox size={28} className="text-green-500" />
          </div>
          <h2 className="text-lg font-semibold text-gray-900 mb-1">All caught up!</h2>
          <p className="text-sm text-gray-500">No actions for today. Check back tomorrow.</p>
        </div>
      )}

      {/* Email section */}
      {emailItems.length > 0 && (
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            <Mail size={16} className="text-amber-600" />
            Email ({emailItems.length})
          </h2>
          <div className="space-y-3">
            {emailItems.map((item, i) => (
              <div key={`${item.contact_id}-email`} ref={(el) => setCardRef(i, el)}>
                <QueueEmailCard
                  item={item}
                  campaign={item.campaign_name || ""}
                  onDeferred={handleDeferred}
                  isFocused={focusedIndex === i}
                  isApproved={approvedIds.has(item.contact_id)}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* LinkedIn section */}
      {linkedinItems.length > 0 && (
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            <Linkedin size={16} className="text-blue-600" />
            LinkedIn ({linkedinItems.length})
          </h2>
          <div className="space-y-3">
            {linkedinItems.map((item, i) => {
              const flatIdx = emailItems.length + i;
              return (
                <div key={`${item.contact_id}-li`} ref={(el) => setCardRef(flatIdx, el)}>
                  <QueueLinkedInCard
                    item={item}
                    campaign={item.campaign_name || ""}
                    onDeferred={handleDeferred}
                    isFocused={focusedIndex === flatIdx}
                    isApproved={approvedIds.has(item.contact_id)}
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {hasApprovals && (
        <div className="fixed bottom-0 left-56 right-0 bg-white border-t border-gray-200 px-6 py-3 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)] z-40">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-gray-700">
                {approvedIds.size} approved
              </span>
              {sendProgress && (
                <span className="text-sm text-blue-600">{sendProgress}</span>
              )}
              {sendResult && (
                <span className={`text-sm ${sendResult.failed > 0 ? "text-amber-600" : "text-green-600"}`}>
                  {sendResult.failed > 0
                    ? `${sendResult.sent} sent, ${sendResult.failed} failed`
                    : `All ${sendResult.sent} sent`}
                </span>
              )}
              {sendMutation.isError && (
                <span className="text-sm text-red-600">
                  {(sendMutation.error as Error).message}
                </span>
              )}
              {scheduleMutation.isError && (
                <span className="text-sm text-red-600">
                  {(scheduleMutation.error as Error).message}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {sendResult && sendResult.failed > 0 && (
                <Button
                  variant="secondary"
                  size="md"
                  onClick={() => sendMutation.mutate()}
                  disabled={sendMutation.isPending}
                >
                  Retry failed
                </Button>
              )}
              <div className="relative" ref={scheduleRef}>
                <button
                  type="button"
                  onClick={() => setScheduleOpen((prev) => !prev)}
                  disabled={scheduleMutation.isPending}
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
                          onClick={() => { scheduleMutation.mutate(preset.value); }}
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
                        onClick={() => { scheduleMutation.mutate(new Date(customDateTime).toISOString()); }}
                        className="mt-2 w-full bg-blue-600 text-white rounded text-sm font-medium px-3 py-1.5 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        Schedule for this time
                      </button>
                    </div>
                  </div>
                )}
              </div>
              <Button
                variant="primary"
                size="lg"
                onClick={() => sendMutation.mutate()}
                loading={sendMutation.isPending}
                leftIcon={<Send size={16} />}
              >
                Send {approvedIds.size} now
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
