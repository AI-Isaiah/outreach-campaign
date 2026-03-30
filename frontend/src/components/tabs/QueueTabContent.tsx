import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, Linkedin, Inbox, X } from "lucide-react";
import { queueApi } from "../../api/queue";
import { queryKeys } from "../../api/queryKeys";
import type { QueueItem, QueueResponse } from "../../types";
import { SkeletonCard } from "../Skeleton";
import ErrorCard from "../ui/ErrorCard";
import QueueEmailCard from "../QueueEmailCard";
import QueueLinkedInCard from "../QueueLinkedInCard";

const HINT_STORAGE_KEY = "queue_keyboard_hint_seen_count";
const MAX_HINT_VIEWS = 3;

export default function QueueTabContent({ campaignName }: { campaignName: string }) {
  const [focusedIndex, setFocusedIndex] = useState(0);
  const [queueScope, setQueueScope] = useState<"all" | "today" | "overdue">("all");
  const [showHint, setShowHint] = useState(() => {
    const count = parseInt(localStorage.getItem(HINT_STORAGE_KEY) || "0", 10);
    return count < MAX_HINT_VIEWS;
  });
  const cardRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const queryClient = useQueryClient();

  const { data, isLoading, isError, error, refetch } = useQuery<QueueResponse>({
    queryKey: [...queryKeys.queue.campaign(campaignName), queueScope],
    queryFn: () => queueApi.getQueue(campaignName, { limit: 50, scope: queueScope }),
  });

  const allItems: QueueItem[] = data?.items || [];
  const totalEnrolled: number = (data as any)?.total_enrolled ?? 0;
  const emailItems = allItems.filter((i) => i.channel === "email");
  const linkedinItems = allItems.filter((i) => i.channel.startsWith("linkedin"));
  const flatItems = useMemo(
    () => [...emailItems, ...linkedinItems],
    [allItems],
  );

  const handleDeferred = useCallback(
    () => queryClient.invalidateQueries({ queryKey: queryKeys.queue.campaign(campaignName) }),
    [queryClient, campaignName],
  );

  useEffect(() => {
    if (flatItems.length > 0 && focusedIndex >= flatItems.length) {
      setFocusedIndex(flatItems.length - 1);
    }
  }, [flatItems.length, focusedIndex]);

  useEffect(() => {
    if (flatItems.length === 0) return;
    const idx = Math.min(focusedIndex, flatItems.length - 1);
    const el = cardRefs.current.get(idx);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [focusedIndex, flatItems.length]);

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
  }, [flatItems, focusedIndex, emailItems.length, linkedinItems.length]);

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

  if (isLoading) {
    return (
      <div className="space-y-4">
        <SkeletonCard /><SkeletonCard /><SkeletonCard />
      </div>
    );
  }

  if (isError) {
    return <ErrorCard message={(error as Error).message} onRetry={() => refetch()} />;
  }

  const scopePills = (
    <div className="flex gap-2 mb-4">
      {(["all", "today", "overdue"] as const).map((scope) => (
        <button
          key={scope}
          onClick={() => setQueueScope(scope)}
          className={`rounded-full px-3 py-1 text-sm font-medium transition-colors ${
            queueScope === scope
              ? "bg-gray-900 text-white"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200"
          }`}
        >
          {scope === "all" && "All Queued"}
          {scope === "today" && `Due today (${new Date().toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })})`}
          {scope === "overdue" && "Overdue"}
        </button>
      ))}
    </div>
  );

  if (allItems.length === 0) {
    // Distinguish "no contacts at all" from "contacts enrolled but filtered out"
    const hasEnrolled = totalEnrolled > 0;
    let title: string;
    let subtitle: string;
    if (queueScope === "overdue") {
      title = "Nothing overdue. Nice.";
      subtitle = "All outreach is on schedule.";
    } else if (queueScope === "today") {
      title = hasEnrolled ? "All caught up!" : "No contacts enrolled yet";
      subtitle = hasEnrolled
        ? "No actions for today. Check back tomorrow."
        : "Enroll contacts to start seeing queue items.";
    } else if (hasEnrolled) {
      title = `${totalEnrolled} contacts enrolled, but none match the queue`;
      subtitle = "Contacts may need email verification, or their next action date hasn't arrived yet. Check the Contacts tab for details.";
    } else {
      title = "No contacts enrolled yet";
      subtitle = "Enroll contacts to start seeing queue items.";
    }

    return (
      <div>
        {scopePills}
        <div className="text-center py-16">
          <div className={`w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4 ${hasEnrolled && queueScope === "all" ? "bg-amber-50" : "bg-green-50"}`}>
            <Inbox size={28} className={hasEnrolled && queueScope === "all" ? "text-amber-500" : "text-green-500"} />
          </div>
          <h2 className="text-lg font-semibold text-gray-900 mb-1">{title}</h2>
          <p className="text-sm text-gray-500 max-w-md mx-auto">{subtitle}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {scopePills}
      <p className="text-sm text-gray-500">
        {allItems.length} action{allItems.length !== 1 ? "s" : ""} today
        {emailItems.length > 0 && ` \u00b7 ${emailItems.length} email`}
        {linkedinItems.length > 0 && ` \u00b7 ${linkedinItems.length} LinkedIn`}
      </p>

      {showHint && flatItems.length > 0 && (
        <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-2 text-sm text-blue-700 flex items-center justify-between">
          <span>
            Navigate with{" "}
            <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">j</kbd>
            /
            <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">k</kbd>
            {" \u00b7 "}
            <kbd className="font-mono bg-white border border-blue-200 rounded px-1.5 py-0.5 text-xs">Tab</kbd>
            {" to switch sections"}
          </span>
          <button
            onClick={dismissHint}
            className="text-blue-400 hover:text-blue-600 ml-3 flex-shrink-0"
            aria-label="Dismiss keyboard hints"
          >
            <X size={16} />
          </button>
        </div>
      )}

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
                  campaign={campaignName}
                  onDeferred={handleDeferred}
                  isFocused={focusedIndex === i}
                />
              </div>
            ))}
          </div>
        </div>
      )}

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
                    campaign={campaignName}
                    onDeferred={handleDeferred}
                    isFocused={focusedIndex === flatIdx}
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
