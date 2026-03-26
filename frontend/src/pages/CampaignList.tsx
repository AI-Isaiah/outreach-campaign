import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Megaphone, Plus, Rocket } from "lucide-react";
import { campaignsApi } from "../api/campaigns";
import type { CampaignWithMetrics } from "../api/campaigns";
import StatusBadge from "../components/StatusBadge";
import { SkeletonCard } from "../components/Skeleton";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";
import HealthScoreBadge from "../components/HealthScoreBadge";

export default function CampaignList() {
  const { data, isLoading, isError, error, refetch } = useQuery<CampaignWithMetrics[]>({
    queryKey: ["campaigns"],
    queryFn: campaignsApi.listCampaigns,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Campaigns</h1>
          {data && data.length > 0 && (
            <p className="text-sm text-gray-500 mt-1">
              {data.length} campaign{data.length !== 1 ? "s" : ""}
            </p>
          )}
        </div>
        <Link to="/campaigns/wizard">
          <Button variant="primary" size="md" leftIcon={<Plus size={16} />}>
            New Campaign
          </Button>
        </Link>
      </div>

      {isLoading && (
        <div className="space-y-4">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {isError && (
        <ErrorCard
          message={(error as Error).message}
          onRetry={() => refetch()}
        />
      )}

      {data && data.length > 0 ? (
        <div className="space-y-3">
          {data.map((c) => (
            <CampaignCard key={c.id} campaign={c} />
          ))}
        </div>
      ) : (
        !isLoading && !isError && <EmptyState />
      )}
    </div>
  );
}

const STATUS_DOT_COLORS: Record<string, string> = {
  active: "bg-green-500",
  draft: "bg-gray-300",
  completed: "bg-blue-500",
};

function CampaignCard({ campaign: c }: { campaign: CampaignWithMetrics }) {
  const statusDotColor = STATUS_DOT_COLORS[c.status] || "bg-yellow-500";

  const channels = c.description || "Email + LinkedIn";
  const createdDate = c.created_at?.split("T")[0] || "";

  return (
    <Link
      to={`/campaigns/${c.name}`}
      className="block border border-gray-200 rounded-lg p-5 hover:shadow-sm transition-shadow bg-white"
    >
      <div className="flex items-start gap-4">
        <div className={`w-2.5 h-2.5 rounded-full mt-1.5 shrink-0 ${statusDotColor}`} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-gray-900 truncate">{c.name}</h3>
            <StatusBadge status={c.status} />
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            {channels} &middot; Started {createdDate}
          </p>
        </div>

        <div className="flex gap-6 shrink-0 items-center">
          <Metric label="Contacts" value={c.contacts_count ?? 0} />
          <Metric label="Reply Rate" value={`${c.reply_rate ?? 0}%`} />
          <Metric label="Calls" value={c.calls_booked ?? 0} />
          <HealthScoreBadge score={c.health_score} />
        </div>

        <div className="w-28 shrink-0 mt-1">
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                c.status === "completed" ? "bg-blue-500" : "bg-green-500"
              }`}
              style={{ width: `${Math.min(c.progress_pct ?? 0, 100)}%` }}
            />
          </div>
          <span className="text-xs text-gray-400 mt-0.5 block text-right">
            {Math.round(c.progress_pct ?? 0)}%
          </span>
        </div>
      </div>
    </Link>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="text-center">
      <div className="text-lg font-bold text-gray-900">{value}</div>
      <div className="text-xs text-gray-400 uppercase tracking-wide">{label}</div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="text-center py-16 px-6">
      <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center mx-auto mb-4">
        <Megaphone size={28} className="text-gray-400" />
      </div>
      <h2 className="text-lg font-semibold text-gray-900 mb-1">
        Create your first campaign
      </h2>
      <p className="text-sm text-gray-500 mb-6 max-w-md mx-auto">
        Upload contacts, build a sequence, and start reaching out via email and LinkedIn.
      </p>
      <Link to="/campaigns/wizard">
        <Button variant="primary" size="lg" leftIcon={<Rocket size={16} />}>
          Create Campaign
        </Button>
      </Link>
    </div>
  );
}
