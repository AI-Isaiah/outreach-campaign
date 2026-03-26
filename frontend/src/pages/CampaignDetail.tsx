import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Trophy } from "lucide-react";
import { campaignsApi } from "../api/campaigns";
import type { CampaignContact } from "../api/campaigns";
import { api } from "../api/client";
import type { CampaignMetricsResponse, TemplatePerformanceItem } from "../types";
import MetricCard from "../components/MetricCard";
import StatusBadge from "../components/StatusBadge";
import { SkeletonCard, SkeletonTable } from "../components/Skeleton";
import ErrorCard from "../components/ui/ErrorCard";
import HealthScoreBadge from "../components/HealthScoreBadge";

type Tab = "contacts" | "messages" | "sequence" | "analytics";

const TABS: { key: Tab; label: string }[] = [
  { key: "contacts", label: "Contacts" },
  { key: "messages", label: "Messages" },
  { key: "sequence", label: "Sequence" },
  { key: "analytics", label: "Analytics" },
];

export default function CampaignDetail() {
  const { name } = useParams<{ name: string }>();
  const [activeTab, setActiveTab] = useState<Tab>("contacts");

  const { data: metricsData, isLoading: metricsLoading, error: metricsError, refetch: refetchMetrics } = useQuery<CampaignMetricsResponse>({
    queryKey: ["campaign-metrics", name],
    queryFn: () => api.getCampaignMetrics(name as string),
    enabled: !!name,
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
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Contacted"
          value={metrics.emails_sent + metrics.linkedin_connects}
          accent="green"
        />
        <MetricCard
          label="Replied"
          value={(metrics.by_status?.replied_positive || 0) + (metrics.by_status?.replied_negative || 0)}
          accent="blue"
        />
        <MetricCard
          label="Waiting"
          value={metrics.by_status?.in_progress || 0}
          accent="yellow"
        />
        <MetricCard
          label="Calls Booked"
          value={metrics.calls_booked}
          accent="green"
        />
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
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" aria-label={`${activeTab} tab content`}>
        {activeTab === "contacts" && <ContactsTab campaignName={name!} campaignId={campaign.id} />}
        {activeTab === "messages" && <MessagesTab />}
        {activeTab === "sequence" && <SequenceTab />}
        {activeTab === "analytics" && <AnalyticsTab metricsData={metricsData} campaignName={name!} />}
      </div>
    </div>
  );
}

// ─── Contacts Tab ──────────────────────────────────────────────────

function ContactsTab({ campaignName, campaignId }: { campaignName: string; campaignId: number }) {
  const [statusFilter, setStatusFilter] = useState<string>("");

  const { data, isLoading, isError, error, refetch } = useQuery<CampaignContact[]>({
    queryKey: ["campaign-contacts", campaignId, statusFilter],
    queryFn: () => campaignsApi.getCampaignContacts(campaignId, {
      status: statusFilter || undefined,
      sort: "step",
    }),
  });

  if (isLoading) return <SkeletonTable rows={5} cols={5} />;
  if (isError) return <ErrorCard message={(error as Error).message} onRetry={() => refetch()} />;

  return (
    <div className="space-y-4">
      {/* Filter */}
      <div className="flex gap-2">
        {["", "queued", "in_progress", "replied_positive", "replied_negative", "no_response", "bounced", "completed", "unsubscribed"].map((s) => (
          <button
            key={s}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              statusFilter === s
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
            onClick={() => setStatusFilter(s)}
          >
            {s === "" ? "All" : s.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      {data && data.length > 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Contact</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Company</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Step</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.map((c) => (
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
                    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                      Step {c.current_step} of {c.total_steps}
                    </span>
                  </td>
                  <td className="px-5 py-4"><StatusBadge status={c.status} /></td>
                  <td className="px-5 py-4">
                    <Link
                      to={`/contacts/${c.id}?campaign=${campaignName}`}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      View
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center py-12 text-sm text-gray-500">
          {statusFilter ? "No contacts with this status." : "No contacts enrolled yet."}
        </div>
      )}
    </div>
  );
}

// ─── Messages Tab ──────────────────────────────────────────────────

function MessagesTab() {
  return (
    <div className="text-center py-12 text-sm text-gray-500">
      No messages sent yet. Launch the campaign to start outreach.
    </div>
  );
}

// ─── Sequence Tab ──────────────────────────────────────────────────

function SequenceTab() {
  return (
    <div className="text-center py-12 text-sm text-gray-500">
      No sequence steps defined.
    </div>
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
                  <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                    t.channel === "email" ? "bg-blue-100 text-blue-700" : "bg-indigo-100 text-indigo-700"
                  }`}>
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
