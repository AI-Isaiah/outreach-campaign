import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { QueueItem } from "../types";
import QueueEmailCard from "../components/QueueEmailCard";
import QueueLinkedInCard from "../components/QueueLinkedInCard";

const DEFAULT_CAMPAIGN = "Q1_2026_initial";

export default function Queue() {
  const [campaign, setCampaign] = useState(DEFAULT_CAMPAIGN);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["queue", campaign],
    queryFn: () => api.getQueue(campaign),
  });

  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: api.listCampaigns,
  });

  const batchDraft = useMutation({
    mutationFn: () => api.createBatchDrafts(campaign),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
  });

  const items: QueueItem[] = data?.items || [];
  const emailItems = items.filter((i) => i.channel === "email");
  const linkedinItems = items.filter((i) => i.channel.startsWith("linkedin"));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Today's Queue</h1>
          <p className="text-gray-500 mt-1">
            {items.length} action{items.length !== 1 ? "s" : ""} ready
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={campaign}
            onChange={(e) => setCampaign(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-md text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {campaigns.data?.map((c: any) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            )) || <option value={DEFAULT_CAMPAIGN}>{DEFAULT_CAMPAIGN}</option>}
          </select>
          {emailItems.length > 0 && (
            <button
              onClick={() => batchDraft.mutate()}
              disabled={batchDraft.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {batchDraft.isPending
                ? "Creating..."
                : `Push All Drafts (${emailItems.length})`}
            </button>
          )}
        </div>
      </div>

      {isLoading && (
        <div className="text-center py-12 text-gray-400">Loading queue...</div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
          {(error as Error).message}
        </div>
      )}

      {!isLoading && items.length === 0 && (
        <div className="text-center py-16">
          <p className="text-gray-400 text-lg">No actions queued for today</p>
          <p className="text-gray-300 text-sm mt-1">
            All caught up! Check back tomorrow.
          </p>
        </div>
      )}

      {/* LinkedIn actions */}
      {linkedinItems.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-3">
            LinkedIn ({linkedinItems.length})
          </h2>
          <div className="space-y-4">
            {linkedinItems.map((item) => (
              <QueueLinkedInCard
                key={item.contact_id}
                item={item}
                campaign={campaign}
              />
            ))}
          </div>
        </div>
      )}

      {/* Email actions */}
      {emailItems.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-gray-900 mb-3">
            Email ({emailItems.length})
          </h2>
          <div className="space-y-4">
            {emailItems.map((item) => (
              <QueueEmailCard
                key={item.contact_id}
                item={item}
                campaign={campaign}
              />
            ))}
          </div>
        </div>
      )}

      {batchDraft.isError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
          Batch draft error: {(batchDraft.error as Error).message}
        </div>
      )}
      {batchDraft.isSuccess && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-green-700 text-sm">
          Batch drafts created successfully.
        </div>
      )}
    </div>
  );
}
