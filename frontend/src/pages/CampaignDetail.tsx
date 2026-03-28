import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { useParams, Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight,
  Trophy,
  MoreVertical,
  Play,
  Pause,
  Archive,
  Trash2,
  Mail,
  Linkedin,
  Inbox,
  X,
  ListOrdered,
  MessageSquare,
} from "lucide-react";
import { campaignsApi } from "../api/campaigns";
import type { CampaignContact } from "../api/campaigns";
import { queueApi } from "../api/queue";
import { api } from "../api/client";
import { request } from "../api/request";
import { queryKeys } from "../api/queryKeys";
import type { CampaignMetricsResponse, TemplatePerformanceItem, QueueItem, QueueResponse } from "../types";
import MetricCard from "../components/MetricCard";
import StatusBadge from "../components/StatusBadge";
import { SkeletonCard, SkeletonTable } from "../components/Skeleton";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";
import HealthScoreBadge from "../components/HealthScoreBadge";
import QueueEmailCard from "../components/QueueEmailCard";
import QueueLinkedInCard from "../components/QueueLinkedInCard";
import SequenceEditorDetail from "../components/SequenceEditorDetail";
import type { SequenceStep } from "../components/SequenceEditorDetail";
import { useToast } from "../components/Toast";
import { CHANNEL_LABELS } from "../constants";
import { channelBadgeClass } from "../utils/sequenceUtils";
import CrmContactPicker from "./campaigns/components/CrmContactPicker";

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
            <HealthScoreBadge score={campaign.health_score} />
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
        <button className="text-left" onClick={() => { switchTab("contacts"); setSearchParams({}, { replace: true }); }}>
          <MetricCard
            label="Emails Sent"
            value={metrics.emails_sent ?? 0}
            accent="green"
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
        {activeTab === "contacts" && <ContactsTab campaignName={name!} campaignId={campaign.id} onSwitchTab={switchTab} />}
        {activeTab === "queue" && <QueueTab campaignName={name!} />}
        {activeTab === "messages" && <MessagesTab campaignId={campaign.id} />}
        {activeTab === "sequence" && <SequenceTab campaignName={campaign.name} campaignId={campaign.id} />}
        {activeTab === "analytics" && <AnalyticsTab metricsData={metricsData} campaignName={name!} />}
      </div>
    </div>
  );
}

// ─── Contacts Tab ──────────────────────────────────────────────────

const CONTACT_STATUS_FILTERS = [
  "", "queued", "in_progress", "replied_positive", "replied_negative",
  "no_response", "bounced", "completed", "unsubscribed",
] as const;

function ContactsTab({ campaignName, campaignId, onSwitchTab }: { campaignName: string; campaignId: number; onSwitchTab: (tab: Tab) => void }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const filterParam = searchParams.get("filter") || "";
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [sortField, setSortField] = useState<string>("step");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [showAddContacts, setShowAddContacts] = useState(false);
  const [addContactIds, setAddContactIds] = useState<Set<number>>(new Set());
  const queryClient = useQueryClient();
  const { toast } = useToast();

  // Sync metric card filter from URL params
  useEffect(() => {
    if (filterParam === "contacted") setStatusFilter("no_response");
    else if (filterParam === "replied") setStatusFilter("replied_positive");
    else if (filterParam === "in_progress") setStatusFilter("in_progress");
    else if (filterParam) setStatusFilter(filterParam);
  }, [filterParam]);

  const { data, isLoading, isError, error, refetch } = useQuery<CampaignContact[]>({
    queryKey: ["campaign-contacts", campaignId, statusFilter],
    queryFn: () => campaignsApi.getCampaignContacts(campaignId, {
      status: statusFilter || undefined,
      sort: "step",
    }),
  });

  // Client-side sort
  const sortedData = useMemo(() => {
    if (!data) return [];
    const sorted = [...data].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "contact": cmp = (a.full_name || "").localeCompare(b.full_name || ""); break;
        case "company": cmp = (a.company_name || "").localeCompare(b.company_name || ""); break;
        case "step": cmp = a.current_step - b.current_step; break;
        case "status": cmp = a.status.localeCompare(b.status); break;
        default: cmp = 0;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [data, sortField, sortDir]);

  const toggleSort = (field: string) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("asc");
    }
  };

  if (isLoading) return <SkeletonTable rows={5} cols={5} />;
  if (isError) return <ErrorCard message={(error as Error).message} onRetry={() => refetch()} />;

  const SortHeader = ({ field, children }: { field: string; children: React.ReactNode }) => (
    <th
      className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide cursor-pointer hover:text-gray-700 select-none"
      onClick={() => toggleSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {sortField === field && (
          <span className="text-gray-400">{sortDir === "asc" ? "↑" : "↓"}</span>
        )}
      </span>
    </th>
  );

  return (
    <div className="space-y-4">
      {/* Filter + Add Contacts */}
      <div className="flex gap-2 flex-wrap items-center">
        {CONTACT_STATUS_FILTERS.map((s) => (
          <button
            key={s}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              statusFilter === s
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
            onClick={() => { setStatusFilter(s); setSearchParams({}, { replace: true }); }}
          >
            {s === "" ? "All" : s.replace(/_/g, " ")}
          </button>
        ))}
        <button
          onClick={() => setShowAddContacts(!showAddContacts)}
          className="ml-auto px-3 py-1 rounded-full text-xs font-medium bg-blue-600 text-white hover:bg-blue-700 transition-colors"
        >
          + Add Contacts
        </button>
      </div>

      {showAddContacts && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
          <div className="flex justify-between items-center">
            <h3 className="text-sm font-medium text-gray-900">Enroll contacts in this campaign</h3>
            <button onClick={() => setShowAddContacts(false)} className="text-gray-400 hover:text-gray-600 text-xs">Close</button>
          </div>
          <CrmContactPicker selectedIds={addContactIds} onSelectionChange={setAddContactIds} />
          {addContactIds.size > 0 && (
            <div className="flex items-center gap-3">
              <button
                onClick={async () => {
                  try {
                    await campaignsApi.enrollContacts(campaignId, Array.from(addContactIds));
                    queryClient.invalidateQueries({ queryKey: ["campaign-contacts", campaignId] });
                    queryClient.invalidateQueries({ queryKey: ["campaign-detail"] });
                    toast(`Enrolled ${addContactIds.size} contact${addContactIds.size !== 1 ? "s" : ""}`, "success");
                    setAddContactIds(new Set());
                    setShowAddContacts(false);
                  } catch (err: unknown) {
                    toast((err as Error).message || "Failed to enroll contacts", "error");
                  }
                }}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
              >
                Enroll {addContactIds.size} Contact{addContactIds.size !== 1 ? "s" : ""}
              </button>
              <span className="text-xs text-gray-500">{addContactIds.size} selected</span>
            </div>
          )}
        </div>
      )}

      {sortedData.length > 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <SortHeader field="contact">Contact</SortHeader>
                <SortHeader field="company">Company</SortHeader>
                <SortHeader field="step">Step</SortHeader>
                <SortHeader field="status">Status</SortHeader>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sortedData.map((c) => (
                <tr key={c.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-5 py-4">
                    <Link
                      to={`/contacts/${c.id}?campaign=${campaignName}`}
                      className="font-medium text-gray-900 hover:text-blue-600"
                    >
                      {c.full_name || `${c.first_name} ${c.last_name}`}
                    </Link>
                    {c.title && <p className="text-xs text-gray-400">{c.title}</p>}
                  </td>
                  <td className="px-5 py-4 text-sm text-gray-500">{c.company_name}</td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          onSwitchTab("queue");
                        }}
                        className={`text-xs font-medium px-2 py-0.5 rounded cursor-pointer hover:opacity-80 transition-opacity ${channelBadgeClass(c.current_channel || "")}`}
                        title={`View in queue`}
                      >
                        {CHANNEL_LABELS[c.current_channel || ""] ?? `Step ${c.current_step}`}
                      </button>
                      <span className="text-xs text-gray-400">{c.current_step}/{c.total_steps}</span>
                    </div>
                  </td>
                  <td className="px-5 py-4"><StatusBadge status={c.status} /></td>
                  <td className="px-5 py-4 flex gap-2">
                    <button
                      onClick={() => onSwitchTab("queue")}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      Queue
                    </button>
                    <Link
                      to={`/contacts/${c.id}?campaign=${campaignName}`}
                      className="text-xs text-gray-400 hover:underline"
                    >
                      Profile
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center py-12 text-sm text-gray-500">
          {statusFilter ? "No contacts with this status." : (
            <div className="space-y-3">
              <p>No contacts enrolled yet.</p>
              <button
                onClick={() => setShowAddContacts(true)}
                className="px-4 py-2 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors"
              >
                Add Contacts
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Queue Tab ────────────────────────────────────────────────────

const HINT_STORAGE_KEY = "queue_keyboard_hint_seen_count";
const MAX_HINT_VIEWS = 3;

function QueueTab({ campaignName }: { campaignName: string }) {
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
    queryFn: () => queueApi.getQueue(campaignName, { limit: 50, scope: queueScope === "all" ? undefined : queueScope }),
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

// ─── Messages Tab ──────────────────────────────────────────────────

function ReplyBadge({ status }: { status: string }) {
  if (status === "replied_positive") {
    return <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500" title="Positive reply" />;
  }
  if (status === "replied_negative") {
    return <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-500" title="Negative reply" />;
  }
  return <span className="inline-block w-2.5 h-2.5 rounded-full bg-gray-300" title="No reply" />;
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  email_sent: "Email",
  linkedin_connect: "LinkedIn Connect",
  linkedin_message: "LinkedIn Message",
  linkedin_engage: "LinkedIn Engage",
  linkedin_insight: "LinkedIn Insight",
  linkedin_final: "LinkedIn Final",
};

function MessagesTab({ campaignId }: { campaignId: number }) {
  const [offset, setOffset] = useState(0);
  const { data, isLoading } = useQuery({
    queryKey: ["campaign-messages", campaignId, offset],
    queryFn: () => campaignsApi.getCampaignMessages(campaignId, { limit: 25, offset }),
  });

  if (isLoading) return <SkeletonTable rows={3} cols={5} />;

  const messages = data?.messages || [];
  const total = data?.total || 0;

  if (!messages.length) {
    return (
      <div className="text-center py-16">
        <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center mx-auto mb-4">
          <MessageSquare size={24} className="text-blue-500" />
        </div>
        <h3 className="text-lg font-semibold text-gray-900 mb-1">No messages sent yet</h3>
        <p className="text-sm text-gray-500">Queue and send to see history.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <table className="w-full">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr>
            <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Contact</th>
            <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Channel</th>
            <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Subject / Action</th>
            <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Sent</th>
            <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Reply</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {messages.map((msg: any) => (
            <tr key={msg.id} className="hover:bg-gray-50 transition-colors">
              <td className="px-5 py-4 text-sm font-medium text-gray-900">{msg.contact_name}</td>
              <td className="px-5 py-4 text-sm text-gray-500">
                {EVENT_TYPE_LABELS[msg.event_type] ?? msg.event_type?.replace(/_/g, " ") ?? "\u2014"}
              </td>
              <td className="px-5 py-4 text-sm text-gray-500">{msg.template_subject || "\u2014"}</td>
              <td className="px-5 py-4 text-sm text-gray-500">{new Date(msg.sent_at).toLocaleDateString()}</td>
              <td className="px-5 py-4">
                <ReplyBadge status={msg.reply_status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {messages.length < total && (
        <div className="px-5 py-3 border-t border-gray-100 text-center">
          <button
            onClick={() => setOffset((prev) => prev + 25)}
            className="text-sm font-medium text-blue-600 hover:text-blue-700"
          >
            Load more ({messages.length} of {total})
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Sequence Tab ──────────────────────────────────────────────────

function SequenceTab({ campaignName, campaignId }: { campaignName: string; campaignId: number }) {
  const { data: steps, isLoading } = useQuery<SequenceStep[]>({
    queryKey: ["campaign-sequence", campaignId],
    queryFn: () => request<SequenceStep[]>(`/campaigns/${campaignId}/sequence`),
    enabled: !!campaignId,
  });

  const { data: contactsData } = useQuery<CampaignContact[]>({
    queryKey: ["campaign-contacts-count", campaignId],
    queryFn: () => campaignsApi.getCampaignContacts(campaignId),
  });
  const enrolledCount = contactsData?.length ?? 0;

  if (isLoading) return <SkeletonTable rows={3} cols={4} />;

  if (!steps || steps.length === 0) {
    return (
      <div className="text-center py-12">
        <div className="w-12 h-12 rounded-full bg-purple-50 flex items-center justify-center mx-auto mb-3">
          <ListOrdered size={24} className="text-purple-500" />
        </div>
        <h3 className="text-sm font-semibold text-gray-900 mb-1">No sequence set up</h3>
        <p className="text-sm text-gray-500 mb-4">
          Add a message sequence to automate your outreach for this campaign.
        </p>
        <a
          href={`/campaigns/wizard?campaign=${encodeURIComponent(campaignName)}`}
          className="inline-flex items-center gap-1.5 bg-gray-900 text-white rounded-lg px-4 py-2 text-sm font-medium hover:bg-gray-800"
        >
          Set Up Sequence
        </a>
      </div>
    );
  }

  return (
    <SequenceEditorDetail
      campaignId={campaignId}
      steps={steps}
      enrolledCount={enrolledCount}
    />
  );
}

// ─── Analytics Tab ─────────────────────────────────────────────────

function AnalyticsTab({ metricsData, campaignName }: { metricsData: CampaignMetricsResponse; campaignName: string }) {
  const { metrics, variants, weekly } = metricsData;
  const bs = metrics?.by_status || {};
  const rb = metrics?.reply_breakdown;

  const { data: templatePerf, isLoading: tpLoading, error: tpError, refetch: tpRefetch } = useQuery<TemplatePerformanceItem[]>({
    queryKey: ["template-performance", campaignName],
    queryFn: () => api.getTemplatePerformance(campaignName),
    enabled: !!campaignName,
    staleTime: 60_000,
  });

  if (metrics.total_enrolled < 10) {
    return (
      <div className="text-center py-12 text-sm text-gray-500">
        Not enough data yet. Enroll 10+ contacts to see analytics.
      </div>
    );
  }

  const hasReplies = rb && rb.total > 0;
  const hasTemplateData = templatePerf && templatePerf.length > 0;
  const bothEmpty = !hasReplies && !tpLoading && !hasTemplateData;

  return (
    <div className="space-y-6">
      {/* Status breakdown */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Status Breakdown</h3>
        <div className="grid grid-cols-3 md:grid-cols-6 gap-4 text-center">
          {Object.entries(bs).map(([status, count]) => (
            <div key={status}>
              <p className="text-2xl font-bold">{count as number}</p>
              <p className="text-xs text-gray-500 capitalize">{status.replace(/_/g, " ")}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Reply breakdown */}
      {bothEmpty ? (
        <div className="text-center py-8 text-sm text-gray-400">
          Outreach is running — replies and template insights will appear here as contacts respond.
        </div>
      ) : (
        <>
          <ReplyBreakdownCard positive={rb?.positive ?? 0} negative={rb?.negative ?? 0} />

          {/* Weekly summary */}
          {weekly && (
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-gray-900 mb-1">This Week</h3>
              <p className="text-xs text-gray-400 mb-4">{weekly.period}</p>
              <div className="grid grid-cols-3 md:grid-cols-5 gap-4 text-center">
                <div>
                  <p className="text-xl font-bold">{weekly.emails_sent}</p>
                  <p className="text-xs text-gray-500">Emails</p>
                </div>
                <div>
                  <p className="text-xl font-bold">{weekly.linkedin_actions}</p>
                  <p className="text-xs text-gray-500">LinkedIn</p>
                </div>
                <div>
                  <p className="text-xl font-bold text-green-600">{weekly.replies_positive}</p>
                  <p className="text-xs text-gray-500">Positive</p>
                </div>
                <div>
                  <p className="text-xl font-bold text-red-500">{weekly.replies_negative}</p>
                  <p className="text-xs text-gray-500">Negative</p>
                </div>
                <div>
                  <p className="text-xl font-bold text-blue-600">{weekly.calls_booked}</p>
                  <p className="text-xs text-gray-500">Calls</p>
                </div>
              </div>
            </div>
          )}

          {/* Template performance */}
          <TemplatePerformanceTable data={templatePerf ?? []} isLoading={tpLoading} error={tpError} onRetry={() => tpRefetch()} />
        </>
      )}

      {/* A/B Variants */}
      {(variants || []).length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h3 className="text-sm font-semibold text-gray-900">A/B Variant Comparison</h3>
          </div>
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">Variant</th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">Total</th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">Reply Rate</th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">Positive Rate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {variants.map((v) => (
                <tr key={v.variant}>
                  <td className="px-5 py-3 font-medium">{v.variant}</td>
                  <td className="px-5 py-3 text-right">{v.total}</td>
                  <td className="px-5 py-3 text-right">{(v.reply_rate * 100).toFixed(1)}%</td>
                  <td className="px-5 py-3 text-right">{(v.positive_rate * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Reply Breakdown Card ─────────────────────────────────────────

function ReplyBreakdownCard({ positive, negative }: { positive: number; negative: number }) {
  const total = positive + negative;

  if (total === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Reply Breakdown</h3>
        <p className="text-sm text-gray-400">No replies yet. Replies will appear as contacts respond.</p>
      </div>
    );
  }

  const positivePct = Math.round((positive / total) * 100);
  const negativePct = 100 - positivePct;

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5">
      <h3 className="text-sm font-semibold text-gray-900 mb-4">Reply Breakdown</h3>
      <div className="flex gap-6 mb-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-600 shrink-0" />
          <span className="text-2xl font-bold">{positive}</span>
          <span className="text-xs text-gray-500">Positive</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-red-600 shrink-0" />
          <span className="text-2xl font-bold">{negative}</span>
          <span className="text-xs text-gray-500">Negative</span>
        </div>
      </div>
      <div
        className="h-7 rounded-md overflow-hidden flex"
        role="img"
        aria-label={`Reply breakdown: ${positive} positive (${positivePct}%), ${negative} negative (${negativePct}%)`}
      >
        {positive > 0 && (
          <div
            className="bg-green-600 flex items-center justify-center text-white text-xs font-semibold min-w-[24px]"
            style={{ width: `${positivePct}%` }}
          >
            {positivePct >= 15 ? `${positivePct}%` : ""}
          </div>
        )}
        {negative > 0 && (
          <div
            className="bg-red-600 flex items-center justify-center text-white text-xs font-semibold min-w-[24px]"
            style={{ width: `${negativePct}%` }}
          >
            {negativePct >= 15 ? `${negativePct}%` : ""}
          </div>
        )}
      </div>
      {/* External labels for tiny segments */}
      {(positivePct > 0 && positivePct < 15) || (negativePct > 0 && negativePct < 15) ? (
        <div className="flex justify-between mt-1 text-xs text-gray-500">
          <span>{positivePct}% positive</span>
          <span>{negativePct}% negative</span>
        </div>
      ) : null}
    </div>
  );
}

// ─── Template Performance Table ───────────────────────────────────

function rateColorClass(rate: number): string {
  if (rate >= 0.5) return "text-green-600 font-semibold";
  if (rate >= 0.3) return "text-amber-600 font-semibold";
  return "text-red-600 font-semibold";
}

function TemplatePerformanceTable({
  data, isLoading, error, onRetry,
}: {
  data: TemplatePerformanceItem[];
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  if (isLoading) return <SkeletonTable rows={3} cols={5} />;
  if (error) return <ErrorCard message={error.message} onRetry={onRetry} />;
  if (!data || data.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Template Performance</h3>
        <p className="text-sm text-gray-400">No templates used yet.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden overflow-x-auto">
      <div className="px-5 py-4 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-900">Template Performance</h3>
      </div>
      <table className="w-full">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-200">
            <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Template</th>
            <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Channel</th>
            <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Sends</th>
            <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Rate</th>
            <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide hidden md:table-cell">Confidence</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {data.map((t) => {
            const resolved = t.positive + t.negative;
            const showRate = t.total_sends >= 10 && resolved > 0;
            return (
              <tr key={t.template_id} className="hover:bg-gray-50 transition-colors">
                <td className="px-5 py-4">
                  <span className="text-sm font-medium text-gray-900">{t.template_name}</span>
                  {t.is_winning && (
                    <span className="ml-2 inline-flex items-center gap-1 bg-green-100 text-green-800 px-2 py-0.5 rounded-full text-xs font-medium">
                      <Trophy size={12} />
                      Winning
                    </span>
                  )}
                </td>
                <td className="px-5 py-4">
                  <span className={`text-xs font-medium px-2 py-0.5 rounded ${channelBadgeClass(t.channel)}`}>
                    {t.channel === "email" ? "Email" : "LinkedIn"}
                  </span>
                </td>
                <td className="px-5 py-4 text-right text-sm text-gray-700">{t.total_sends}</td>
                <td className="px-5 py-4 text-right text-sm" aria-label={showRate ? `${(t.positive_rate * 100).toFixed(1)}% positive reply rate` : undefined}>
                  {showRate ? (
                    <span className={rateColorClass(t.positive_rate)}>
                      {(t.positive_rate * 100).toFixed(0)}%
                    </span>
                  ) : (
                    <span className="text-gray-400" title={resolved === 0 ? "Awaiting replies" : "Not enough sends"}>—</span>
                  )}
                </td>
                <td className="px-5 py-4 text-right text-sm text-gray-500 capitalize hidden md:table-cell">{t.confidence}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
