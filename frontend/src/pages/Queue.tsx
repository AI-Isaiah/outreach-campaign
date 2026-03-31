import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, Inbox, X } from "lucide-react";
import { queueApi } from "../api/queue";
import { queryKeys } from "../api/queryKeys";
import { api } from "../api/client";
import type { QueueItem, QueueResponse } from "../types";
import ReviewGateModal from "../components/ReviewGateModal";
import { useBatchSendLoop } from "../hooks/useBatchSendLoop";
import { SkeletonCard } from "../components/Skeleton";
import ErrorBoundary from "../components/ErrorBoundary";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";
import KeyboardHint from "./queue/KeyboardHint";
import FilterBar from "./queue/FilterBar";
import type { ChannelFilter } from "./queue/FilterBar";
import StickyActionBar from "./queue/StickyActionBar";
import CardSection from "./queue/CardSection";

const HINT_STORAGE_KEY = "queue_keyboard_hint_seen_count";
const MAX_HINT_VIEWS = 3;

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

  const cardRefs = useRef<Map<number, HTMLDivElement>>(new Map());
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
    onSuccess: () => {
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: queryKeys.queue.all });
    },
  });

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

      <FilterBar
        channelFilter={channelFilter}
        onChannelFilterChange={setChannelFilter}
        campaignFilter={campaignFilter}
        onCampaignFilterChange={setCampaignFilter}
        campaignNames={campaignNames}
      />

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
        <CardSection
          emailItems={emailItems}
          linkedinItems={linkedinItems}
          focusedIndex={focusedIndex}
          selectedIds={selectedIds}
          onToggle={toggleSelected}
          onDeferred={handleDeferred}
          setCardRef={setCardRef}
        />
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

      {/* Sticky Bottom Bar */}
      {showStickyBar && (
        <StickyActionBar
          selectedCount={selectedIds.size}
          sendPhase={sendPhase}
          sendProgress={sendProgress}
          undoCountdown={undoCountdown}
          schedulePending={scheduleMutation.isPending}
          scheduleError={scheduleMutation.isError ? (scheduleMutation.error as Error) : null}
          onDeselectAll={() => setSelectedIds(new Set())}
          onReview={() => setShowReviewModal(true)}
          onCancel={handleCancel}
          onUndo={handleUndo}
          onReset={resetState}
          onSchedule={(value) => scheduleMutation.mutate(value)}
        />
      )}
    </div>
  );
}
