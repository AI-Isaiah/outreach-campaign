import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, Inbox, Mail, Linkedin, X } from "lucide-react";
import { queueApi } from "../api/queue";
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
          if (item) {
            setApprovedIds((prev) => {
              const next = new Set(prev);
              if (next.has(item.contact_id)) {
                next.delete(item.contact_id);
              } else {
                next.add(item.contact_id);
              }
              return next;
            });
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
  }, [flatItems, focusedIndex, emailItems.length, linkedinItems.length, skipMutation]);

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

  return (
    <div className="space-y-6" role="application" aria-label="Outreach queue">
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
    </div>
  );
}
