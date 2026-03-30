import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Archive, Megaphone, MoreVertical, Plus, Rocket, Search, Trash2, RotateCcw } from "lucide-react";
import { campaignsApi } from "../api/campaigns";
import type { CampaignWithMetrics } from "../api/campaigns";
import { queryKeys } from "../api/queryKeys";
import StatusBadge from "../components/StatusBadge";
import { SkeletonCard } from "../components/Skeleton";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";
import HealthScoreBadge from "../components/HealthScoreBadge";
import ConfirmDialog from "../components/ConfirmDialog";

type ViewMode = "active" | "archived";

export default function CampaignList() {
  const [viewMode, setViewMode] = useState<ViewMode>("active");
  const [searchQuery, setSearchQuery] = useState("");
  const queryClient = useQueryClient();

  const { data, isLoading, isError, error, refetch } = useQuery<CampaignWithMetrics[]>({
    queryKey: [...queryKeys.campaigns.all, viewMode],
    queryFn: () => campaignsApi.listCampaigns(viewMode === "archived" ? "archived" : undefined),
  });

  const filtered = useMemo(() => {
    if (!data) return [];
    if (!searchQuery) return data;
    const q = searchQuery.toLowerCase();
    return data.filter((c) => c.name.toLowerCase().includes(q));
  }, [data, searchQuery]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Campaigns</h1>
          {data && (
            <p className="text-sm text-gray-500 mt-1">
              {filtered.length} campaign{filtered.length !== 1 ? "s" : ""}
              {searchQuery && ` matching "${searchQuery}"`}
            </p>
          )}
        </div>
        <Link to="/campaigns/wizard">
          <Button variant="primary" size="md" leftIcon={<Plus size={16} />}>
            New Campaign
          </Button>
        </Link>
      </div>

      {/* Search + Active/Archived toggle */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search campaigns..."
            className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
        <div className="flex rounded-lg border border-gray-200 overflow-hidden">
          <button
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              viewMode === "active"
                ? "bg-gray-900 text-white"
                : "bg-white text-gray-600 hover:bg-gray-50"
            }`}
            onClick={() => setViewMode("active")}
          >
            Active
          </button>
          <button
            className={`px-4 py-2 text-sm font-medium transition-colors border-l border-gray-200 ${
              viewMode === "archived"
                ? "bg-gray-900 text-white"
                : "bg-white text-gray-600 hover:bg-gray-50"
            }`}
            onClick={() => setViewMode("archived")}
          >
            Archived
          </button>
        </div>
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

      {filtered.length > 0 ? (
        <div className="space-y-3">
          {filtered.map((c) => (
            <CampaignCard key={c.id} campaign={c} viewMode={viewMode} />
          ))}
        </div>
      ) : (
        !isLoading && !isError && (
          data && data.length === 0 && !searchQuery
            ? (viewMode === "archived" ? <ArchivedEmpty /> : <EmptyState />)
            : searchQuery
              ? <p className="text-center py-12 text-sm text-gray-500">No campaigns matching "{searchQuery}"</p>
              : null
        )
      )}
    </div>
  );
}

const STATUS_DOT_COLORS: Record<string, string> = {
  active: "bg-green-500",
  draft: "bg-gray-300",
  completed: "bg-blue-500",
  archived: "bg-gray-400",
};

function CampaignCard({ campaign: c, viewMode }: { campaign: CampaignWithMetrics; viewMode: ViewMode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const queryClient = useQueryClient();

  const archiveMutation = useMutation({
    mutationFn: () => campaignsApi.updateCampaignStatus(c.name, "archived"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all }),
  });

  const restoreMutation = useMutation({
    mutationFn: () => campaignsApi.updateCampaignStatus(c.name, "active"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => campaignsApi.deleteCampaign(c.name),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all }),
  });

  const statusDotColor = STATUS_DOT_COLORS[c.status] || "bg-yellow-500";
  const channels = c.description || "Email + LinkedIn";
  const createdDate = c.created_at?.split("T")[0] || "";

  return (
    <div className="border border-gray-200 rounded-lg p-5 bg-white hover:shadow-sm transition-shadow relative">
      <div className="flex items-start gap-4">
        <Link to={c.status === "draft" ? `/campaigns/wizard?editCampaign=${c.id}&step=2` : `/campaigns/${c.name}`} className="flex-1 min-w-0 flex items-start gap-4">
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
            <Metric label="Sent" value={c.emails_sent ?? 0} />
            <HealthScoreBadge score={c.health_score} totalSent={c.emails_sent} />
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
        </Link>

        {/* Actions menu */}
        <div className="relative shrink-0">
          <button
            onClick={(e) => { e.preventDefault(); setMenuOpen(!menuOpen); }}
            className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600"
            aria-label="Campaign actions"
          >
            <MoreVertical size={16} />
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 top-8 w-40 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-50">
                {viewMode === "active" ? (
                  <button
                    onClick={() => { archiveMutation.mutate(); setMenuOpen(false); }}
                    className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                  >
                    <Archive size={14} /> Archive
                  </button>
                ) : (
                  <button
                    onClick={() => { restoreMutation.mutate(); setMenuOpen(false); }}
                    className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                  >
                    <RotateCcw size={14} /> Restore
                  </button>
                )}
                <button
                  onClick={() => {
                    setMenuOpen(false);
                    setConfirmDeleteOpen(true);
                  }}
                  className="w-full text-left px-3 py-2 text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
                >
                  <Trash2 size={14} /> Delete
                </button>
              </div>
            </>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete Campaign"
        message={`Delete "${c.name}"? This removes all enrollments and sequence steps permanently.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={() => {
          deleteMutation.mutate();
          setConfirmDeleteOpen(false);
        }}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </div>
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

function ArchivedEmpty() {
  return (
    <div className="text-center py-12 text-sm text-gray-500">
      No archived campaigns.
    </div>
  );
}
