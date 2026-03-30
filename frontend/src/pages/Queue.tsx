import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Calendar, CheckCircle, ChevronDown, Clock, Inbox, Info, Loader2, Mail, Linkedin, Send, X } from "lucide-react";
import { queueApi } from "../api/queue";
import { queryKeys } from "../api/queryKeys";
import { SCHEDULE_PRESETS } from "../constants";
import { api } from "../api/client";
import type { QueueItem, QueueResponse } from "../types";
import QueueEmailCard from "../components/QueueEmailCard";
import QueueLinkedInCard from "../components/QueueLinkedInCard";
import ReviewGateModal from "../components/ReviewGateModal";
import { useBatchSendLoop } from "../hooks/useBatchSendLoop";
import { SkeletonCard } from "../components/Skeleton";
import ErrorBoundary from "../components/ErrorBoundary";
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
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">Space</kbd>
        {" to select \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">s</kbd>
        {" to skip \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">Ctrl+Enter</kbd>
        {" to review & send"}
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
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [showHint, setShowHint] = useState(() => {
    const count = parseInt(localStorage.getItem(HINT_STORAGE_KEY) || "0", 10);
    return count < MAX_HINT_VIEWS;
  });
  const [showReviewModal, setShowReviewModal] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [customDateTime, setCustomDateTime] = useState("");

  const cardRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const scheduleRef = useRef<HTMLDivElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const {
    sendPhase,
    sendProgress,
    validationErrors,
    undoCountdown,
    handleConfirmSend,
    handleCancel,
    handleUndo,
    resetState,
  } = useBatchSendLoop();

  const { data, isLoading, isError, error, refetch } = useQuery<QueueResponse>({
    queryKey: queryKeys.queue.all,
    queryFn: () => queueApi.getAllQueues({ limit: 50 }),
  });

  const batchDraft = useMutation({
    mutationFn: () => api.createBatchDrafts(campaignFilter),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.queue.all }),
  });

  const skipMutation = useMutation({
    mutationFn: ({ contactId, campaign }: { contactId: number; campaign: string }) =>
      queueApi.deferContact(contactId, campaign, "skipped_via_keyboard"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.queue.all });
      queryClient.invalidateQueries({ queryKey: ["defer-stats"] });
    },
  });

  const scheduleMutation = useMutation({
    mutationFn: (schedule: string) => {
      const selectedPairs = flatItems
        .filter((i) => selectedIds.has(i.contact_id) && i.campaign_id)
        .map((i) => ({ contact_id: i.contact_id, campaign_id: i.campaign_id! }));
      return queueApi.scheduleSend(selectedPairs, schedule);
    },
    onSuccess: (result) => {
      setSelectedIds(new Set());
      setScheduleOpen(false);
      setCustomDateTime("");
      queryClient.invalidateQueries({ queryKey: queryKeys.queue.all });
    },
  });

  // Close schedule dropdown on outside click
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
  const items = useMemo(() => {
    let filtered = allItems;
    if (channelFilter === "email") {
      filtered = filtered.filter((i) => i.channel === "email");
    } else if (channelFilter === "linkedin") {
      filtered = filtered.filter((i) => i.channel.startsWith("linkedin"));
    }
    if (campaignFilter) {
      filtered = filtered.filter((i) => i.campaign_name === campaignFilter);
    }
    return filtered;
  }, [allItems, channelFilter, campaignFilter]);

  const emailItems = useMemo(() => items.filter((i) => i.channel === "email"), [items]);
  const linkedinItems = useMemo(() => items.filter((i) => i.channel.startsWith("linkedin")), [items]);

  const flatItems = useMemo(
    () => [...emailItems, ...linkedinItems],
    [emailItems, linkedinItems]
  );

  const handleDeferred = useCallback(
    () => queryClient.invalidateQueries({ queryKey: queryKeys.queue.all }),
    [queryClient],
  );

  const campaignNames = useMemo(
    () => [...new Set(allItems.map((i) => i.campaign_name).filter((n): n is string => !!n))],
    [allItems],
  );

  // Clamp focused index
  useEffect(() => {
    if (flatItems.length > 0 && focusedIndex >= flatItems.length) {
      setFocusedIndex(flatItems.length - 1);
    }
  }, [flatItems.length, focusedIndex]);

  // Hint view counter
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

  // Select All indeterminate state
  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selectedIds.size > 0 && selectedIds.size < flatItems.length;
    }
  }, [selectedIds.size, flatItems.length]);

  // beforeunload warning during active send
  useEffect(() => {
    if (sendPhase !== "sending") return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [sendPhase]);

  // Clear selectedIds after send completes
  useEffect(() => {
    if (sendPhase === "done") {
      setSelectedIds(new Set());
    }
  }, [sendPhase]);

  // Toggle selection for a single item
  const toggleSelected = useCallback((contactId: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(contactId)) {
        next.delete(contactId);
      } else {
        next.add(contactId);
      }
      return next;
    });
  }, []);

  // Select All / Deselect All
  const toggleSelectAll = useCallback(() => {
    if (selectedIds.size === flatItems.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(flatItems.map((i) => i.contact_id)));
    }
  }, [flatItems, selectedIds.size]);

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

      // Block queue shortcuts when review modal is open
      if (showReviewModal) return;

      if (flatItems.length === 0) return;

      const maxIndex = flatItems.length - 1;

      // Ctrl+Enter: open review gate
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        if (selectedIds.size > 0) setShowReviewModal(true);
        return;
      }

      // Escape: deselect all
      if (e.key === "Escape") {
        e.preventDefault();
        setSelectedIds(new Set());
        return;
      }

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
        case "Enter":
        case " ": {
          e.preventDefault();
          const idx = Math.min(focusedIndex, maxIndex);
          const item = flatItems[idx];
          if (item) toggleSelected(item.contact_id);
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
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [flatItems, focusedIndex, emailItems.length, linkedinItems.length, skipMutation, selectedIds, showReviewModal, toggleSelected]);

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

  const selectedItems = useMemo(
    () => flatItems.filter((i) => selectedIds.has(i.contact_id)),
    [flatItems, selectedIds],
  );

  const hasSelections = selectedIds.size > 0;
  const showStickyBar = hasSelections || sendPhase !== "idle";

  return (
    <div className={`space-y-6 ${showStickyBar ? "pb-20" : ""}`} role="application" aria-label="Outreach queue">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Today's Queue</h1>
          <p className="text-sm text-gray-500 mt-1">
            {allItems.length} action{allItems.length !== 1 ? "s" : ""} across {campaignNames.length} campaign{campaignNames.length !== 1 ? "s" : ""}
            {emailItems.length > 0 && ` \u00b7 ${emailItems.length} email`}
            {linkedinItems.length > 0 && ` \u00b7 ${linkedinItems.length} LinkedIn`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Select All */}
          {flatItems.length > 0 && (
            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
              <input
                ref={selectAllRef}
                type="checkbox"
                checked={selectedIds.size === flatItems.length && flatItems.length > 0}
                onChange={toggleSelectAll}
                className="w-4 h-4 accent-blue-600"
                aria-label="Select all queue items"
              />
              Select All
            </label>
          )}
          {selectedIds.size > 0 && (
            <span className="bg-blue-100 text-blue-700 text-xs font-medium px-2 py-0.5 rounded-full" aria-live="polite">
              {selectedIds.size} selected
            </span>
          )}
          {emailItems.length > 0 && (
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
          )}
          {batchDraft.isError && (
            <span className="text-red-500 text-sm">
              {(batchDraft.error as Error).message}
            </span>
          )}
        </div>
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

        {campaignNames.length > 0 && (
          <>
            <div className="w-px bg-gray-200 mx-1" />
            <select
              value={campaignFilter}
              onChange={(e) => setCampaignFilter(e.target.value)}
              className="px-3 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 border-0 cursor-pointer hover:bg-gray-200 transition-colors appearance-none pr-6"
              style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")", backgroundRepeat: "no-repeat", backgroundPosition: "right 6px center" }}
            >
              <option value="">All campaigns ({campaignNames.length})</option>
              {campaignNames.map((cn) => (
                <option key={cn} value={cn}>{cn}</option>
              ))}
            </select>
          </>
        )}
      </div>

      {showHint && flatItems.length > 0 && <KeyboardHint onDismiss={dismissHint} />}

      {skipMutation.isError && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 text-sm text-red-700 flex items-center justify-between">
          <span>Skip failed: {(skipMutation.error as Error).message}</span>
          <button onClick={() => skipMutation.reset()} className="text-red-400 hover:text-red-600 ml-3 flex-shrink-0" aria-label="Dismiss error">
            <X size={16} />
          </button>
        </div>
      )}

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

      <ErrorBoundary>
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

                    isSelected={selectedIds.has(item.contact_id)}
                    onToggle={toggleSelected}
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

                      isSelected={selectedIds.has(item.contact_id)}
                      onToggle={toggleSelected}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </ErrorBoundary>

      {/* Review Gate Modal */}
      <ReviewGateModal
        open={showReviewModal}
        onClose={() => { setShowReviewModal(false); }}
        selectedItems={selectedItems}
        onConfirmSend={(force) => {
          setShowReviewModal(false);
          handleConfirmSend(force, flatItems, selectedIds);
        }}
        validationErrors={validationErrors}
        isConfirming={sendPhase === "approving"}
        scheduleMode={null}
      />

      {/* Sticky Bottom Bar — 5-state display */}
      {showStickyBar && (
        <div className="fixed bottom-0 left-0 md:left-56 right-0 bg-white border-t border-gray-200 px-6 py-3 shadow-[0_-4px_6px_-1px_rgba(0,0,0,0.05)] z-40" aria-live="polite">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            {/* Left side — status */}
            <div className="flex items-center gap-3">
              {sendPhase === "idle" && (
                <>
                  <span className="text-sm font-medium text-gray-700">
                    {selectedIds.size} selected
                  </span>
                  <button
                    onClick={() => setSelectedIds(new Set())}
                    className="text-xs text-blue-600 hover:text-blue-700 underline"
                  >
                    Deselect all
                  </button>
                </>
              )}
              {sendPhase === "approving" && (
                <span className="flex items-center gap-2 text-sm text-gray-500">
                  <Loader2 size={14} className="animate-spin" /> Validating...
                </span>
              )}
              {sendPhase === "sending" && sendProgress && (
                <span className="flex items-center gap-2 text-sm text-blue-600">
                  <Loader2 size={14} className="animate-spin" />
                  Sending... {sendProgress.sent} of {sendProgress.total}
                  <span title="If interrupted, unsent items stay in your queue."><Info size={14} className="text-gray-400" /></span>
                </span>
              )}
              {sendPhase === "done" && sendProgress && (
                <span className={`text-sm font-medium ${sendProgress.failed > 0 ? "text-amber-600" : "text-green-600"}`}>
                  {sendProgress.failed > 0
                    ? `${sendProgress.sent} sent, ${sendProgress.failed} failed`
                    : `${sendProgress.sent} sent`}
                </span>
              )}
              {sendPhase === "aborted" && sendProgress && (
                <span className="text-sm text-amber-600">
                  Cancelled. {sendProgress.sent} of {sendProgress.total} sent. Remaining items still in queue.
                </span>
              )}
              {sendPhase === "error" && (
                <span className="text-sm text-red-600">
                  Send failed. {sendProgress ? `${sendProgress.sent} sent before error.` : ""}
                </span>
              )}
              {scheduleMutation.isError && (
                <span className="text-sm text-red-600">
                  {(scheduleMutation.error as Error).message}
                </span>
              )}
            </div>

            {/* Right side — actions */}
            <div className="flex items-center gap-2">
              {/* Sending: Cancel button */}
              {sendPhase === "sending" && (
                <Button variant="secondary" size="md" onClick={handleCancel}>
                  Cancel
                </Button>
              )}

              {/* Done: Undo + Retry */}
              {sendPhase === "done" && undoCountdown !== null && undoCountdown > 0 && (
                <Button variant="secondary" size="md" onClick={handleUndo}>
                  Undo ({undoCountdown}s)
                </Button>
              )}
              {sendPhase === "done" && sendProgress && sendProgress.failed > 0 && (
                <Button variant="secondary" size="md" onClick={() => resetState()}>
                  Retry failed
                </Button>
              )}

              {/* Aborted/Error: Reset */}
              {(sendPhase === "aborted" || sendPhase === "error") && (
                <Button variant="secondary" size="md" onClick={resetState}>
                  Dismiss
                </Button>
              )}

              {/* Idle: Schedule + Review & Send */}
              {sendPhase === "idle" && hasSelections && (
                <>
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
                    onClick={() => setShowReviewModal(true)}
                    leftIcon={<Send size={16} />}
                  >
                    Review & Send {selectedIds.size}
                  </Button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
