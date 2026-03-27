import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Calendar, CheckCircle, ChevronDown, Clock, Inbox, Mail, Linkedin, Send, WifiOff, X } from "lucide-react";
import { queueApi } from "../api/queue";
import { queryKeys } from "../api/queryKeys";
import { SCHEDULE_PRESETS } from "../constants";
import { api } from "../api/client";
import type { QueueItem, QueueResponse } from "../types";
import QueueEmailCard from "../components/QueueEmailCard";
import QueueLinkedInCard from "../components/QueueLinkedInCard";
import QueueBatchHeader from "../components/QueueBatchHeader";
import ReviewGateModal from "../components/ReviewGateModal";
import UndoToast from "../components/UndoToast";
import { SkeletonCard } from "../components/Skeleton";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";
import { useShortcutManager } from "../hooks/useShortcutManager";
import { useQueueCache } from "../hooks/useQueueCache";
import { useAuth } from "../context/AuthContext";
import { logQueueEvent } from "../utils/queueTelemetry";

const HINT_STORAGE_KEY = "queue_keyboard_hint_seen_count";
const MAX_HINT_VIEWS = 3;
const QUEUE_V2_KEY = "queue_v2_enabled";
const APPROVED_IDS_KEY = "queue-approved-ids";
const UNDO_WINDOW_MS = 30_000;

function KeyboardHint({ onDismiss, isV2 = false }: { onDismiss: () => void; isV2?: boolean }) {
  return (
    <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-2 text-sm text-blue-700 flex items-center justify-between">
      <span>
        Navigate with{" "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">j</kbd>
        /
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">k</kbd>
        {" \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">Enter</kbd>
        {isV2 ? " to toggle" : " to approve"}
        {isV2 && (
          <>
            {" \u00b7 "}
            <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">x</kbd>
            {" to select"}
          </>
        )}
        {" \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">s</kbd>
        {" to skip \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">e</kbd>
        {" to edit \u00b7 "}
        <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">Tab</kbd>
        {" to switch sections"}
        {isV2 && (
          <>
            {" \u00b7 "}
            <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">Shift+Enter</kbd>
            {" to review & send"}
          </>
        )}
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
  const [isV2] = useState(() => localStorage.getItem(QUEUE_V2_KEY) !== "false");
  const [channelFilter, setChannelFilter] = useState<ChannelFilter>("all");
  const [campaignFilter, setCampaignFilter] = useState<string>("");
  const [focusedIndex, setFocusedIndex] = useState(0);
  const [reviewGateOpen, setReviewGateOpen] = useState(false);
  const [undoState, setUndoState] = useState<{ contactIds: number[]; count: number } | null>(null);
  const [limboIds, setLimboIds] = useState<Set<number>>(new Set());

  const { user } = useAuth();
  const { writeCache, readCache, clearCache, getCacheAge } = useQueueCache(user?.id ?? 0);
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);

  // Track online/offline events
  useEffect(() => {
    const goOnline = () => setIsOnline(true);
    const goOffline = () => setIsOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  // Initialize approvedIds from localStorage (V2) or empty set (legacy)
  const [approvedIds, setApprovedIds] = useState<Set<number>>(() => {
    if (!isV2) return new Set();
    try {
      const stored = localStorage.getItem(APPROVED_IDS_KEY);
      if (stored) return new Set(JSON.parse(stored));
    } catch {}
    return new Set();
  });

  const [showHint, setShowHint] = useState(() => {
    const count = parseInt(localStorage.getItem(HINT_STORAGE_KEY) || "0", 10);
    return count < MAX_HINT_VIEWS;
  });
  const cardRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const approvedIdsRef = useRef(approvedIds);
  approvedIdsRef.current = approvedIds;
  const sendButtonRef = useRef<HTMLButtonElement>(null);
  const queryClient = useQueryClient();

  // Persist approvedIds to localStorage on change (V2 only)
  useEffect(() => {
    if (!isV2) return;
    localStorage.setItem(APPROVED_IDS_KEY, JSON.stringify([...approvedIds]));
  }, [approvedIds, isV2]);

  const { data, isLoading, isError, error, refetch } = useQuery<QueueResponse>({
    queryKey: queryKeys.queue.all,
    queryFn: () => queueApi.getAllQueues({ limit: 50 }),
  });

  // Write cache on successful fetch
  useEffect(() => {
    if (data?.items && data.items.length > 0) {
      writeCache(data.items, data.total);
    }
  }, [data, writeCache]);

  // Fallback to cache on error — compute both in one read to avoid TTL race
  const { cachedFallback, cacheAge } = useMemo(() => {
    if (!isError) return { cachedFallback: null, cacheAge: null };
    const cached = readCache();
    if (!cached) return { cachedFallback: null, cacheAge: null };
    const age = Math.round((Date.now() - cached.timestamp) / 60000);
    return { cachedFallback: cached, cacheAge: age };
  }, [isError, readCache]);

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
      queryClient.invalidateQueries({ queryKey: queryKeys.queue.all });
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
      queryClient.invalidateQueries({ queryKey: queryKeys.queue.all });
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

  const usingCache = isError && cachedFallback != null;

  // Telemetry: cache hit
  useEffect(() => {
    if (usingCache && cacheAge != null) {
      logQueueEvent({ type: "queue.cache_hit", age_minutes: cacheAge });
    }
  }, [usingCache, cacheAge]);

  // Use live data when available, fall back to cached metadata on error
  const allItems: QueueItem[] = data?.items || (usingCache
    ? cachedFallback.items.map((c) => ({
        contact_id: c.contact_id,
        contact_name: c.contact_name,
        company_name: c.company_name,
        company_id: 0,
        aum_millions: null,
        firm_type: null,
        aum_tier: "",
        channel: c.channel,
        step_order: c.step_order,
        total_steps: 0,
        template_id: null,
        is_gdpr: false,
        email: null,
        linkedin_url: null,
        campaign_name: c.campaign_name ?? undefined,
        campaign_id: c.campaign_id ?? undefined,
        has_research: c.has_research,
      } satisfies QueueItem))
    : []);

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
    () => queryClient.invalidateQueries({ queryKey: queryKeys.queue.all }),
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

  // Telemetry: session start
  useEffect(() => {
    logQueueEvent({ type: "queue.session_start" });
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

  const toggleItem = useCallback((contactId: number) => {
    setApprovedIds(prev => {
      const next = new Set(prev);
      if (next.has(contactId)) next.delete(contactId);
      else next.add(contactId);
      return next;
    });
  }, []);

  // Keyboard shortcuts via ShortcutManager
  const { registerShortcut } = useShortcutManager();

  useEffect(() => {
    const unregAll: (() => void)[] = [];

    unregAll.push(registerShortcut("j", () => {
      if (flatItems.length === 0) return;
      setFocusedIndex(prev => Math.min(prev + 1, flatItems.length - 1));
    }, "page"));

    unregAll.push(registerShortcut("k", () => {
      if (flatItems.length === 0) return;
      setFocusedIndex(prev => Math.max(prev - 1, 0));
    }, "page"));

    // Enter: in V2 mode, toggle checkbox. In legacy mode, approve immediately.
    unregAll.push(registerShortcut("Enter", () => {
      if (flatItems.length === 0) return;
      const idx = Math.min(focusedIndex, flatItems.length - 1);
      const item = flatItems[idx];
      if (!item?.campaign_id) return;

      setApprovedIds(prev => {
        const next = new Set(prev);
        const wasSelected = prev.has(item.contact_id);
        if (wasSelected) next.delete(item.contact_id);
        else next.add(item.contact_id);
        // Legacy mode: send approve to server when newly selected
        if (!isV2 && !wasSelected) {
          approveMutation.mutate([{ contact_id: item.contact_id, campaign_id: item.campaign_id! }]);
        }
        return next;
      });
    }, "page"));

    unregAll.push(registerShortcut("s", () => {
      if (flatItems.length === 0) return;
      const idx = Math.min(focusedIndex, flatItems.length - 1);
      const item = flatItems[idx];
      if (item?.campaign_name) {
        skipMutation.mutate({ contactId: item.contact_id, campaign: item.campaign_name });
      }
    }, "page"));

    unregAll.push(registerShortcut("e", () => {
      if (flatItems.length === 0) return;
      const idx = Math.min(focusedIndex, flatItems.length - 1);
      const el = cardRefs.current.get(idx);
      if (el) {
        const editBtn = el.querySelector<HTMLButtonElement>('button[data-role="edit-contact"]');
        if (editBtn) editBtn.click();
      }
    }, "page"));

    unregAll.push(registerShortcut("Tab", () => {
      if (emailItems.length > 0 && linkedinItems.length > 0) {
        const idx = Math.min(focusedIndex, flatItems.length - 1);
        if (idx < emailItems.length) {
          setFocusedIndex(emailItems.length);
        } else {
          setFocusedIndex(0);
        }
      }
    }, "page"));

    // V2-only shortcuts
    if (isV2) {
      unregAll.push(registerShortcut("x", () => {
        if (flatItems.length === 0) return;
        const idx = Math.min(focusedIndex, flatItems.length - 1);
        const item = flatItems[idx];
        if (item) toggleItem(item.contact_id);
      }, "page"));

      unregAll.push(registerShortcut("Shift+Enter", () => {
        // Read from ref to avoid approvedIds in dep array
        if (approvedIdsRef.current.size > 0) {
          setReviewGateOpen(true);
        }
      }, "page"));
    }

    return () => unregAll.forEach(fn => fn());
  }, [flatItems, focusedIndex, emailItems.length, linkedinItems.length, isV2, skipMutation, approveMutation, registerShortcut, toggleItem]);

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

  // -- V2 batch selection handlers --
  const toggleAll = useCallback(() => {
    const visibleIds = flatItems.map(i => i.contact_id);
    setApprovedIds(prev => {
      const allSelected = visibleIds.every(id => prev.has(id));
      if (allSelected) {
        const next = new Set(prev);
        visibleIds.forEach(id => next.delete(id));
        return next;
      } else {
        const next = new Set(prev);
        visibleIds.forEach(id => next.add(id));
        return next;
      }
    });
  }, [flatItems]);

  const selectCampaign = useCallback((campaignName: string) => {
    const campaignIds = flatItems.filter(i => i.campaign_name === campaignName).map(i => i.contact_id);
    setApprovedIds(prev => {
      const next = new Set(prev);
      campaignIds.forEach(id => next.add(id));
      return next;
    });
  }, [flatItems]);

  const deselectAll = useCallback(() => {
    setApprovedIds(new Set());
  }, []);

  // -- V2 review gate confirm handler --
  const handleReviewConfirm = useCallback(async (selectedIds: number[]) => {
    setReviewGateOpen(false);
    logQueueEvent({ type: "queue.review_gate_confirm", count: selectedIds.length });
    // Restore focus to the sticky bar send button
    requestAnimationFrame(() => sendButtonRef.current?.focus());
    setLimboIds(new Set(selectedIds));

    // Chunk into batches of 10
    const chunks: number[][] = [];
    for (let i = 0; i < selectedIds.length; i += 10) {
      chunks.push(selectedIds.slice(i, i + 10));
    }

    let totalSent = 0;
    let totalFailed = 0;
    const allErrors: { contact_id: number; error: string }[] = [];

    try {
      // First: batch approve all
      const approveItems = selectedIds
        .map(id => flatItems.find(item => item.contact_id === id))
        .filter((item): item is QueueItem => item != null && item.campaign_id != null)
        .map(item => ({ contact_id: item.contact_id, campaign_id: item.campaign_id! }));

      await queueApi.batchApprove(approveItems);

      // Then: send all chunks in parallel with 30s delay
      const scheduledFor = new Date(Date.now() + UNDO_WINDOW_MS).toISOString();
      const results = await Promise.allSettled(
        chunks.map(chunk => queueApi.batchSend({ contact_ids: chunk, scheduled_for: scheduledFor }))
      );
      for (const r of results) {
        if (r.status === "fulfilled") {
          totalSent += r.value.sent;
          totalFailed += r.value.failed;
          if (r.value.errors) allErrors.push(...r.value.errors.map((e: { contact_id: number; error: string }) => ({ contact_id: e.contact_id, error: e.error })));
        } else {
          totalFailed += 10; // chunk size
          allErrors.push({ contact_id: 0, error: String(r.reason) });
        }
      }

      logQueueEvent({ type: "queue.batch_send_result", sent: totalSent, failed: totalFailed });

      if (totalFailed > 0) {
        setSendResult({ sent: totalSent, failed: totalFailed, errors: allErrors as any });
      }

      // Show undo toast
      setUndoState({ contactIds: selectedIds, count: selectedIds.length });

    } catch (err) {
      setSendResult({ sent: 0, failed: selectedIds.length, errors: [] });
      setLimboIds(new Set());
    }
  }, [flatItems]);

  const handleUndoComplete = useCallback(() => {
    // 30s passed, emails will send via cron
    setUndoState(null);
    setLimboIds(new Set());
    setApprovedIds(new Set());
    localStorage.removeItem(APPROVED_IDS_KEY);
    clearCache();
    queryClient.invalidateQueries({ queryKey: queryKeys.queue.all });
  }, [queryClient, clearCache]);

  const handleUndoSuccess = useCallback(() => {
    // User clicked undo, emails cancelled
    logQueueEvent({ type: "queue.undo_triggered" });
    setUndoState(null);
    setLimboIds(new Set());
    queryClient.invalidateQueries({ queryKey: queryKeys.queue.all });
    // Restore focus to the sticky bar send button
    requestAnimationFrame(() => sendButtonRef.current?.focus());
  }, [queryClient]);

  const handleUndoDismiss = useCallback(() => {
    setUndoState(null);
    // Restore focus to the sticky bar send button
    requestAnimationFrame(() => sendButtonRef.current?.focus());
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

      {isV2 && flatItems.length > 0 && (
        <QueueBatchHeader
          items={flatItems}
          approvedIds={approvedIds}
          onToggleAll={toggleAll}
          onSelectCampaign={selectCampaign}
          onDeselectAll={deselectAll}
        />
      )}

      {showHint && flatItems.length > 0 && <KeyboardHint onDismiss={dismissHint} isV2={isV2} />}

      {isLoading && (
        <div className="space-y-4">
          <SkeletonCard /><SkeletonCard /><SkeletonCard />
        </div>
      )}

      {!isOnline && (
        <div className="bg-gray-100 border border-gray-200 rounded-lg p-3 flex items-center gap-2">
          <WifiOff size={16} className="text-gray-500 shrink-0" />
          <span className="text-sm text-gray-600">You are offline</span>
        </div>
      )}

      {isError && usingCache && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-center justify-between">
          <span className="text-sm text-amber-700">
            Using cached data{cacheAge != null ? ` (${cacheAge} min ago)` : ""}
          </span>
          <Button variant="secondary" size="sm" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      )}

      {isError && !usingCache && (
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
          <div className="space-y-3" role="feed" aria-busy={isLoading} aria-label="Email queue items">
            {emailItems.map((item, i) => (
              <div key={`${item.contact_id}-email`} ref={(el) => setCardRef(i, el)}>
                <QueueEmailCard
                  item={item}
                  campaign={item.campaign_name || ""}
                  onDeferred={handleDeferred}
                  isFocused={focusedIndex === i}
                  isApproved={approvedIds.has(item.contact_id)}
                  showCheckbox={isV2}
                  isSelected={approvedIds.has(item.contact_id)}
                  onToggleSelect={() => toggleItem(item.contact_id)}
                  limboSeconds={limboIds.has(item.contact_id) ? UNDO_WINDOW_MS / 1000 : null}
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
          <div className="space-y-3" role="feed" aria-busy={isLoading} aria-label="LinkedIn queue items">
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
                    showCheckbox={isV2}
                    isSelected={approvedIds.has(item.contact_id)}
                    onToggleSelect={() => toggleItem(item.contact_id)}
                    limboSeconds={limboIds.has(item.contact_id) ? UNDO_WINDOW_MS / 1000 : null}
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
                ref={sendButtonRef}
                variant="primary"
                size="lg"
                onClick={() => {
                  if (isV2) {
                    logQueueEvent({ type: "queue.review_gate_open", count: approvedIds.size });
                    setReviewGateOpen(true);
                  } else {
                    sendMutation.mutate();
                  }
                }}
                loading={sendMutation.isPending}
                leftIcon={<Send size={16} />}
              >
                {isV2 ? `Review & Send ${approvedIds.size}` : `Send ${approvedIds.size} now`}
              </Button>
            </div>
          </div>
        </div>
      )}

      {reviewGateOpen && (
        <ReviewGateModal
          items={flatItems.filter(i => approvedIds.has(i.contact_id))}
          onConfirm={handleReviewConfirm}
          onClose={() => {
            setReviewGateOpen(false);
            // Restore focus to the sticky bar send button
            requestAnimationFrame(() => sendButtonRef.current?.focus());
          }}
        />
      )}

      {undoState && (
        <UndoToast
          contactIds={undoState.contactIds}
          count={undoState.count}
          onComplete={handleUndoComplete}
          onUndo={handleUndoSuccess}
          onDismiss={handleUndoDismiss}
        />
      )}
    </div>
  );
}
