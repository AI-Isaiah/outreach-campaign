import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle } from "lucide-react";
import { api } from "../api/client";
import type { QueueItem, QueueResponse, Campaign } from "../types";
import QueueEmailCard from "../components/QueueEmailCard";
import QueueLinkedInCard from "../components/QueueLinkedInCard";
import { SkeletonCard } from "../components/Skeleton";
import EmptyState from "../components/EmptyState";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";
import Select from "../components/ui/Select";
import { DEFAULT_CAMPAIGN } from "../constants";

const AUM_RANGES: { label: string; min?: number; max?: number }[] = [
  { label: "All AUM" },
  { label: "$0-100M", min: 0, max: 100 },
  { label: "$100M-500M", min: 100, max: 500 },
  { label: "$500M-1B", min: 500, max: 1000 },
  { label: "$1B+", min: 1000 },
];

export default function Queue() {
  const [campaign, setCampaign] = useState(DEFAULT_CAMPAIGN);
  const [activeFirmType, setActiveFirmType] = useState<string | null>(null);
  const [aumRangeIdx, setAumRangeIdx] = useState(0);
  const queryClient = useQueryClient();

  const aumRange = AUM_RANGES[aumRangeIdx];

  const { data, isLoading, isError, error, refetch } = useQuery<QueueResponse>({
    queryKey: ["queue", campaign, activeFirmType, aumRangeIdx],
    queryFn: () =>
      api.getQueue(campaign, {
        firm_type: activeFirmType || undefined,
        aum_min: aumRange.min,
        aum_max: aumRange.max,
      }),
  });

  const campaigns = useQuery<Campaign[]>({
    queryKey: ["campaigns"],
    queryFn: api.listCampaigns,
  });

  const batchDraft = useMutation({
    mutationFn: () => api.createBatchDrafts(campaign),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
  });

  const items: QueueItem[] = data?.items || [];
  const firmTypeCounts = data?.firm_type_counts || {};
  const emailItems = items.filter((i) => i.channel === "email");
  const linkedinItems = items.filter((i) => i.channel.startsWith("linkedin"));

  // Build tabs sorted by count DESC
  const totalCount = Object.values(firmTypeCounts).reduce((a, b) => a + b, 0);
  const sortedTypes = Object.entries(firmTypeCounts).sort(
    ([, a], [, b]) => b - a,
  );

  return (
    <div className="space-y-6">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Today's Queue</h1>
          <p className="text-sm text-gray-500 mt-1">
            {items.length} action{items.length !== 1 ? "s" : ""} ready
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Select
            value={campaign}
            onChange={(e) => {
              setCampaign(e.target.value);
              setActiveFirmType(null);
              setAumRangeIdx(0);
            }}
          >
            {campaigns.data?.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            )) || <option value={DEFAULT_CAMPAIGN}>{DEFAULT_CAMPAIGN}</option>}
          </Select>
          <Select
            value={aumRangeIdx}
            onChange={(e) => {
              setAumRangeIdx(Number(e.target.value));
              setActiveFirmType(null);
            }}
          >
            {AUM_RANGES.map((r, i) => (
              <option key={r.label} value={i}>
                {r.label}
              </option>
            ))}
          </Select>
          {emailItems.length > 0 && (
            <Button
              variant="accent"
              size="md"
              onClick={() => batchDraft.mutate()}
              loading={batchDraft.isPending}
            >
              Push All Drafts ({emailItems.length})
            </Button>
          )}
        </div>
      </div>

      {/* Firm type tabs */}
      {sortedTypes.length > 0 && (
        <div className="flex flex-wrap gap-1 border-b border-gray-200 pb-px">
          <button
            onClick={() => setActiveFirmType(null)}
            className={`px-3 py-1.5 text-sm font-medium rounded-t-md transition-colors ${
              activeFirmType === null
                ? "bg-white text-blue-600 border border-b-white border-gray-200 -mb-px"
                : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
            }`}
          >
            All ({totalCount})
          </button>
          {sortedTypes.map(([type, count]) => (
            <button
              key={type}
              onClick={() =>
                setActiveFirmType(activeFirmType === type ? null : type)
              }
              className={`px-3 py-1.5 text-sm font-medium rounded-t-md transition-colors ${
                activeFirmType === type
                  ? "bg-white text-blue-600 border border-b-white border-gray-200 -mb-px"
                  : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
              }`}
            >
              {type} ({count})
            </button>
          ))}
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="space-y-4">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {/* Error */}
      {isError && (
        <ErrorCard
          message={(error as Error).message}
          onRetry={() => refetch()}
        />
      )}

      {/* Empty state */}
      {!isLoading && !isError && items.length === 0 && (
        <EmptyState
          icon={<CheckCircle size={40} />}
          title={
            activeFirmType || aumRangeIdx > 0
              ? "No actions match these filters"
              : "Queue is clear"
          }
          description={
            activeFirmType || aumRangeIdx > 0
              ? "Try adjusting your filters."
              : "No actions scheduled for today. Check back tomorrow."
          }
        />
      )}

      {/* LinkedIn actions */}
      {linkedinItems.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="w-2.5 h-2.5 rounded-full bg-green-500" />
            <h2 className="text-lg font-semibold text-gray-900">
              LinkedIn ({linkedinItems.length})
            </h2>
          </div>
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
          <div className="flex items-center gap-2 mb-3">
            <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
            <h2 className="text-lg font-semibold text-gray-900">
              Email ({emailItems.length})
            </h2>
          </div>
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
        <ErrorCard message={`Batch draft error: ${(batchDraft.error as Error).message}`} />
      )}
      {batchDraft.isSuccess && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-green-700 text-sm">
          Batch drafts created successfully.
        </div>
      )}
    </div>
  );
}
