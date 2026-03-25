import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, Inbox, Mail, Linkedin } from "lucide-react";
import { queueApi } from "../api/queue";
import { api } from "../api/client";
import type { QueueItem, QueueResponse } from "../types";
import QueueEmailCard from "../components/QueueEmailCard";
import QueueLinkedInCard from "../components/QueueLinkedInCard";
import { SkeletonCard } from "../components/Skeleton";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";

type ChannelFilter = "all" | "email" | "linkedin";

export default function Queue() {
  const [channelFilter, setChannelFilter] = useState<ChannelFilter>("all");
  const [campaignFilter, setCampaignFilter] = useState<string>("");
  const queryClient = useQueryClient();

  const { data, isLoading, isError, error, refetch } = useQuery<QueueResponse>({
    queryKey: ["queue-all"],
    queryFn: () => queueApi.getAllQueues({ limit: 50 }),
  });

  const batchDraft = useMutation({
    mutationFn: () => api.createBatchDrafts(campaignFilter),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue-all"] }),
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

  const handleDeferred = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["queue-all"] }),
    [queryClient],
  );

  // Get unique campaign names from items
  const campaignNames = [...new Set(allItems.map((i) => i.campaign_name).filter((n): n is string => !!n))];

  return (
    <div className="space-y-6">
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
            {emailItems.map((item) => (
              <QueueEmailCard
                key={`${item.contact_id}-email`}
                item={item}
                campaign={item.campaign_name || ""}
                onDeferred={handleDeferred}
              />
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
            {linkedinItems.map((item) => (
              <QueueLinkedInCard
                key={`${item.contact_id}-li`}
                item={item}
                campaign={item.campaign_name || ""}
                onDeferred={handleDeferred}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
