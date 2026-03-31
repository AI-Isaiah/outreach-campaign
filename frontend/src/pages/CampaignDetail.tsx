import { useState, useCallback, useEffect, useRef } from "react";
import { useParams, Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight,
  MoreVertical,
  Play,
  Pause,
  Archive,
  Trash2,
} from "lucide-react";
import { campaignsApi } from "../api/campaigns";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { CampaignMetricsResponse } from "../types";
import MetricCard from "../components/MetricCard";
import StatusBadge from "../components/StatusBadge";
import { SkeletonCard } from "../components/Skeleton";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";
import HealthScoreBadge from "../components/HealthScoreBadge";
import ErrorBoundary from "../components/ErrorBoundary";
import ContactsTabContent from "../components/tabs/ContactsTabContent";
import QueueTabContent from "../components/tabs/QueueTabContent";
import MessagesTabContent from "../components/tabs/MessagesTabContent";
import SequenceTabContent from "../components/tabs/SequenceTabContent";
import AnalyticsTabContent from "../components/tabs/AnalyticsTabContent";

type Tab = "contacts" | "messages" | "sequence" | "analytics" | "queue";

const TABS: { key: Tab; label: string }[] = [
  { key: "contacts", label: "Contacts" },
  { key: "queue", label: "Queue" },
  { key: "messages", label: "Messages" },
  { key: "sequence", label: "Sequence" },
  { key: "analytics", label: "Analytics" },
];

export default function CampaignDetail() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab") as Tab | null;
  const [activeTab, setActiveTab] = useState<Tab>(
    tabParam && TABS.some((t) => t.key === tabParam) ? tabParam : "contacts",
  );

  const switchTab = useCallback(
    (tab: Tab) => {
      setActiveTab(tab);
      setSearchParams(tab === "contacts" ? {} : { tab }, { replace: true });
    },
    [setSearchParams],
  );

  useEffect(() => {
    if (tabParam && TABS.some((t) => t.key === tabParam) && tabParam !== activeTab) {
      setActiveTab(tabParam);
    }
  }, [tabParam]);

  const queryClient = useQueryClient();

  const { data: metricsData, isLoading: metricsLoading, error: metricsError, refetch: refetchMetrics } = useQuery<CampaignMetricsResponse>({
    queryKey: queryKeys.campaigns.detail(name as string),
    queryFn: () => api.getCampaignMetrics(name as string),
    enabled: !!name,
  });

  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
        setConfirmDelete(false);
      }
    }
    if (menuOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [menuOpen]);

  const statusMutation = useMutation({
    mutationFn: (status: "active" | "paused" | "archived") =>
      campaignsApi.updateCampaignStatus(name!, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.detail(name!) });
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all });
      setMenuOpen(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => campaignsApi.deleteCampaign(name!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns.all });
      navigate("/");
    },
  });

  if (metricsLoading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-64 bg-gray-200 rounded animate-pulse" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard />
        </div>
      </div>
    );
  }

  if (metricsError) {
    return <ErrorCard message={(metricsError as Error).message} onRetry={() => refetchMetrics()} />;
  }

  if (!metricsData) return null;

  const { campaign, metrics } = metricsData;
  const campaignStatus = campaign.status as string;

  return (
    <div className="space-y-6">
      <nav className="flex items-center gap-1.5 text-sm text-gray-500">
        <Link to="/" className="hover:text-gray-900">Campaigns</Link>
        <ChevronRight size={14} />
        <span className="text-gray-900 font-medium">{campaign.name}</span>
      </nav>

      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">{campaign.name}</h1>
            <StatusBadge status={campaign.status} />
            <HealthScoreBadge score={campaign.health_score} totalSent={metrics.emails_sent} />
          </div>
          {campaign.description && (
            <p className="text-sm text-gray-500 mt-1">{campaign.description}</p>
          )}
        </div>

        <div className="relative" ref={menuRef}>
          <button
            onClick={() => { setMenuOpen((prev) => !prev); setConfirmDelete(false); }}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            aria-label="Campaign actions"
            aria-expanded={menuOpen}
          >
            <MoreVertical size={20} />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 w-52 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-50">
              {campaignStatus === "active" && (
                <button
                  onClick={() => statusMutation.mutate("paused")}
                  disabled={statusMutation.isPending}
                  className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2.5 disabled:opacity-50"
                >
                  <Pause size={15} className="text-amber-500" />
                  Pause Campaign
                </button>
              )}
              {(campaignStatus === "paused" || campaignStatus === "archived") && (
                <button
                  onClick={() => statusMutation.mutate("active")}
                  disabled={statusMutation.isPending}
                  className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2.5 disabled:opacity-50"
                >
                  <Play size={15} className="text-green-600" />
                  Resume Campaign
                </button>
              )}
              {campaignStatus !== "archived" && (
                <button
                  onClick={() => statusMutation.mutate("archived")}
                  disabled={statusMutation.isPending}
                  className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2.5 disabled:opacity-50"
                >
                  <Archive size={15} className="text-gray-500" />
                  Archive
                </button>
              )}
              <div className="border-t border-gray-100 my-1" />
              {!confirmDelete ? (
                <button
                  onClick={() => setConfirmDelete(true)}
                  className="w-full text-left px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 flex items-center gap-2.5"
                >
                  <Trash2 size={15} />
                  Delete Campaign
                </button>
              ) : (
                <div className="px-4 py-2.5 space-y-2">
                  <p className="text-xs text-red-600 font-medium">
                    This will permanently delete the campaign and all enrollments.
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => deleteMutation.mutate()}
                      loading={deleteMutation.isPending}
                    >
                      Confirm
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setConfirmDelete(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                  {deleteMutation.isError && (
                    <p className="text-xs text-red-500">{(deleteMutation.error as Error).message}</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <button className="text-left" onClick={() => { switchTab("contacts"); setSearchParams({ filter: "contacted" }, { replace: true }); }}>
          <MetricCard
            label="Contacted"
            value={metrics.emails_sent + metrics.linkedin_connects}
            accent="green"
          />
        </button>
        <button className="text-left" onClick={() => { switchTab("contacts"); setSearchParams({ filter: "replied" }, { replace: true }); }}>
          <MetricCard
            label="Replied"
            value={(metrics.by_status?.replied_positive || 0) + (metrics.by_status?.replied_negative || 0)}
            accent="blue"
          />
        </button>
        <button className="text-left" onClick={() => { switchTab("contacts"); setSearchParams({ filter: "in_progress" }, { replace: true }); }}>
          <MetricCard
            label="Waiting"
            value={metrics.by_status?.in_progress || 0}
            accent="yellow"
          />
        </button>
        <button className="text-left" onClick={() => { switchTab("contacts"); setSearchParams({ filter: "completed" }, { replace: true }); }}>
          <MetricCard
            label="Completed"
            value={metrics.by_status?.completed || 0}
            sub={`of ${metrics.total_enrolled} enrolled`}
          />
        </button>
      </div>

      <div
        className="flex border-b border-gray-200 overflow-x-auto"
        role="tablist"
        aria-label="Campaign sections"
      >
        {TABS.map((tab) => (
          <button
            key={tab.key}
            role="tab"
            aria-selected={activeTab === tab.key}
            className={`px-5 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-colors -mb-px ${
              activeTab === tab.key
                ? "border-gray-900 text-gray-900"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            }`}
            onClick={() => switchTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" aria-label={`${activeTab} tab content`}>
        <ErrorBoundary>
          {activeTab === "contacts" && <ContactsTabContent campaignName={name!} campaignId={campaign.id} onSwitchTab={switchTab} />}
          {activeTab === "queue" && <QueueTabContent campaignName={name!} />}
          {activeTab === "messages" && <MessagesTabContent campaignId={campaign.id} />}
          {activeTab === "sequence" && <SequenceTabContent campaignName={campaign.name} campaignId={campaign.id} />}
          {activeTab === "analytics" && <AnalyticsTabContent metricsData={metricsData} campaignName={name!} />}
        </ErrorBoundary>
      </div>
    </div>
  );
}
