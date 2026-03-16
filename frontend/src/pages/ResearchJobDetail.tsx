import { useState, useMemo } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, Users, RefreshCw, XCircle, CheckCircle, Zap, TrendingUp } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, PieChart, Pie } from "recharts";
import { api } from "../api/client";
import type { ResearchResult, Campaign } from "../types";
import { TERMINAL_STATUSES } from "../types";
import CryptoScoreBadge from "../components/CryptoScoreBadge";
import ResearchProgressBar from "../components/ResearchProgressBar";
import MetricCard from "../components/MetricCard";

const CATEGORY_CONFIG: Record<string, { bg: string; text: string; label: string; color: string }> = {
  confirmed_investor: { bg: "bg-green-100", text: "text-green-700", label: "Confirmed", color: "#16A34A" },
  likely_interested: { bg: "bg-blue-100", text: "text-blue-700", label: "Likely", color: "#2563EB" },
  possible: { bg: "bg-yellow-100", text: "text-yellow-700", label: "Possible", color: "#D97706" },
  no_signal: { bg: "bg-gray-100", text: "text-gray-600", label: "No Signal", color: "#6B7280" },
  unlikely: { bg: "bg-red-100", text: "text-red-700", label: "Unlikely", color: "#DC2626" },
};

const SCORE_COLORS: Record<string, string> = {
  "80-100": "#16A34A",
  "60-79": "#2563EB",
  "40-59": "#D97706",
  "20-39": "#6B7280",
  "0-19": "#DC2626",
};

// ---------------------------------------------------------------------------
// Completion Summary
// ---------------------------------------------------------------------------

function CompletionSummary({
  jobData,
  onBatchImport,
}: {
  jobData: any;
  onBatchImport: () => void;
}) {
  const qualified = (jobData.by_category.confirmed_investor || 0) + (jobData.by_category.likely_interested || 0);
  const total = jobData.job.total_companies;

  return (
    <div className="rounded-xl bg-gradient-to-br from-green-50 to-emerald-50 border border-green-100 p-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <CheckCircle size={20} className="text-green-600" />
            <h3 className="font-semibold text-gray-900">Research Complete</h3>
          </div>
          <p className="text-sm text-gray-600">
            Found <strong className="text-green-700">{qualified}</strong> qualified companies out of {total} researched
            {jobData.total_contacts_discovered > 0 && (
              <> · <strong>{jobData.total_contacts_discovered}</strong> contacts discovered</>
            )}
            {jobData.warm_intro_count > 0 && (
              <> · <strong className="text-amber-700">{jobData.warm_intro_count}</strong> warm intro paths</>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => api.exportResearchResults(jobData.job.id)}
            className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            <Download size={14} /> Export CSV
          </button>
          {qualified > 0 && (
            <button
              onClick={onBatchImport}
              className="flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-xs font-medium text-white hover:bg-green-700"
            >
              <Zap size={14} /> Import {qualified} Qualified
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Batch Import Modal
// ---------------------------------------------------------------------------

function BatchImportModal({
  jobId,
  qualifiedIds,
  onClose,
}: {
  jobId: number;
  qualifiedIds: number[];
  onClose: () => void;
}) {
  const [createDeals, setCreateDeals] = useState(true);
  const [campaignName, setCampaignName] = useState("");
  const queryClient = useQueryClient();

  const { data: campaigns } = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.listCampaigns(),
  });

  const batchMutation = useMutation({
    mutationFn: () =>
      api.batchImport(qualifiedIds, createDeals, campaignName || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["research-job", jobId] });
      // Auto-close after brief success display
      setTimeout(onClose, 2000);
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4">
        <div className="px-6 py-4 border-b border-gray-100">
          <h3 className="text-lg font-semibold text-gray-900">Import to CRM</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {qualifiedIds.length} qualified companies with discovered contacts
          </p>
        </div>

        {!batchMutation.isSuccess ? (
          <div className="px-6 py-5 space-y-4">
            <label className="flex items-center gap-3 rounded-lg border border-gray-200 p-3 cursor-pointer hover:bg-gray-50">
              <input
                type="checkbox"
                checked={createDeals}
                onChange={(e) => setCreateDeals(e.target.checked)}
                className="rounded border-gray-300 text-blue-600"
              />
              <div>
                <p className="text-sm font-medium text-gray-900">Create Pipeline Deals</p>
                <p className="text-xs text-gray-500">Add each company to your deal pipeline</p>
              </div>
            </label>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Enroll in Campaign</label>
              <select
                value={campaignName}
                onChange={(e) => setCampaignName(e.target.value)}
                className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Don't enroll (import only)</option>
                {(campaigns as Campaign[] || []).map((c) => (
                  <option key={c.id} value={c.name}>{c.name}</option>
                ))}
              </select>
            </div>
          </div>
        ) : (
          <div className="px-6 py-8 text-center space-y-3">
            <div className="w-14 h-14 rounded-full bg-green-50 flex items-center justify-center mx-auto">
              <CheckCircle size={28} className="text-green-600" />
            </div>
            <div>
              <p className="text-lg font-semibold text-gray-900">Import Complete</p>
              <div className="text-sm text-gray-600 mt-2 space-y-1">
                <p><strong>{batchMutation.data.imported_contacts}</strong> contacts imported</p>
                {batchMutation.data.deals_created > 0 && (
                  <p><strong>{batchMutation.data.deals_created}</strong> deals created</p>
                )}
                {batchMutation.data.enrolled > 0 && (
                  <p><strong>{batchMutation.data.enrolled}</strong> enrolled in campaign</p>
                )}
                {batchMutation.data.skipped_duplicates > 0 && (
                  <p className="text-gray-400">{batchMutation.data.skipped_duplicates} duplicates skipped</p>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-100">
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            {batchMutation.isSuccess ? "Done" : "Cancel"}
          </button>
          {!batchMutation.isSuccess && (
            <button
              onClick={() => batchMutation.mutate()}
              disabled={batchMutation.isPending}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {batchMutation.isPending ? "Importing..." : "Import Contacts"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result Row
// ---------------------------------------------------------------------------

function ResultRow({ result, selected, onSelect, onExpand }: {
  result: ResearchResult;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  onExpand: () => void;
}) {
  const hasWarmIntros = result.warm_intro_contact_ids && result.warm_intro_contact_ids.length > 0;
  const contactCount = result.discovered_contacts_json?.length || 0;

  return (
    <tr className="hover:bg-gray-50 transition-colors">
      <td className="px-3 py-4">
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => onSelect(e.target.checked)}
          className="rounded border-gray-300 text-blue-600"
          onClick={(e) => e.stopPropagation()}
        />
      </td>
      <td className="px-4 py-4 cursor-pointer" onClick={onExpand}>
        <p className="text-sm font-medium text-gray-900">{result.company_name}</p>
        {result.company_website && (
          <p className="text-xs text-gray-400 truncate max-w-[200px]">{result.company_website}</p>
        )}
      </td>
      <td className="px-4 py-4">
        <CryptoScoreBadge score={result.crypto_score} />
      </td>
      <td className="px-4 py-4">
        {result.category && (
          <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
            CATEGORY_CONFIG[result.category]?.bg || ""} ${CATEGORY_CONFIG[result.category]?.text || ""
          }`}>
            {CATEGORY_CONFIG[result.category]?.label || result.category}
          </span>
        )}
      </td>
      <td className="px-4 py-4">
        <p className="text-sm text-gray-600 line-clamp-2 max-w-xs">{result.evidence_summary || "—"}</p>
      </td>
      <td className="px-4 py-4">
        {contactCount > 0 && (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-gray-600">
            <Users size={13} /> {contactCount}
          </span>
        )}
      </td>
      <td className="px-4 py-4">
        {hasWarmIntros && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
            <TrendingUp size={10} /> Warm
          </span>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Expanded Result Detail (inline)
// ---------------------------------------------------------------------------

function ExpandedResult({ result }: { result: ResearchResult }) {
  const queryClient = useQueryClient();
  const importMutation = useMutation({
    mutationFn: (indices: number[]) => api.importDiscoveredContacts(result.id, indices),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["research-results"] }),
  });

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-base font-semibold text-gray-900">{result.company_name}</h3>
          {result.company_id && (
            <Link to={`/companies/${result.company_id}`} className="text-xs text-blue-600 hover:underline">
              View in CRM
            </Link>
          )}
        </div>
        <CryptoScoreBadge score={result.crypto_score} showLabel />
      </div>

      {result.evidence_summary && (
        <p className="text-sm text-gray-600 bg-gray-50 rounded-lg px-4 py-3">{result.evidence_summary}</p>
      )}

      {result.evidence_json && result.evidence_json.length > 0 && (
        <div className="space-y-2">
          {result.evidence_json.map((ev, i) => (
            <div key={i} className="flex gap-2 text-sm">
              <span className={`shrink-0 mt-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                ev.relevance === "high" ? "bg-green-100 text-green-700" :
                ev.relevance === "medium" ? "bg-yellow-100 text-yellow-700" : "bg-gray-100 text-gray-600"
              }`}>{ev.relevance}</span>
              <div>
                <span className="text-xs text-gray-400">{ev.source}</span>
                <p className="text-gray-700 italic">"{ev.quote}"</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {result.discovered_contacts_json && result.discovered_contacts_json.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Discovered Contacts</h4>
            <button
              onClick={() => importMutation.mutate(result.discovered_contacts_json!.map((_, i) => i))}
              disabled={importMutation.isPending}
              className="rounded bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {importMutation.isPending ? "..." : importMutation.isSuccess ? `Imported ${importMutation.data.imported}` : "Import All"}
            </button>
          </div>
          <div className="bg-gray-50 rounded-lg divide-y divide-gray-100 text-sm">
            {result.discovered_contacts_json.map((c, i) => (
              <div key={i} className="px-3 py-2 flex items-center justify-between">
                <div>
                  <span className="font-medium text-gray-900">{c.name}</span>
                  <span className="text-gray-400 ml-2">{c.title}</span>
                </div>
                <div className="flex gap-3 text-xs text-gray-500">
                  {c.email && <span>{c.email}</span>}
                  {c.linkedin && <a href={c.linkedin} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">LinkedIn</a>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {result.warm_intro_notes && (
        <div className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 whitespace-pre-line">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-600 mb-1">Warm Intros</p>
          {result.warm_intro_notes}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function ResearchJobDetail() {
  const { id } = useParams<{ id: string }>();
  const jobId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [showBatchImport, setShowBatchImport] = useState(false);
  const [filters, setFilters] = useState<{
    category?: string;
    min_score?: number;
    has_warm_intros?: boolean;
    page: number;
  }>({ page: 1 });

  const { data: jobData, isLoading: jobLoading } = useQuery({
    queryKey: ["research-job", jobId],
    queryFn: () => api.getResearchJob(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.job.status;
      return status && !(TERMINAL_STATUSES as readonly string[]).includes(status) ? 3000 : false;
    },
  });

  const { data: resultsData, isLoading: resultsLoading } = useQuery({
    queryKey: ["research-results", jobId, filters],
    queryFn: () => api.getResearchResults(jobId, {
      category: filters.category,
      min_score: filters.min_score,
      has_warm_intros: filters.has_warm_intros,
      page: filters.page,
    }),
    enabled: !!jobData,
  });

  const retryMutation = useMutation({
    mutationFn: () => api.retryResearchJob(jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["research-job", jobId] }),
  });

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelResearchJob(jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["research-job", jobId] }),
  });

  // Memoize derived arrays to avoid re-creating on every render
  const qualifiedIds = useMemo(() =>
    resultsData?.results
      .filter((r) => r.category === "confirmed_investor" || r.category === "likely_interested")
      .filter((r) => r.discovered_contacts_json && r.discovered_contacts_json.length > 0)
      .map((r) => r.id) || [],
    [resultsData],
  );

  const qualifiedSelectedIds = useMemo(() =>
    resultsData?.results
      .filter((r) => selectedIds.has(r.id))
      .filter((r) => r.discovered_contacts_json && r.discovered_contacts_json.length > 0)
      .map((r) => r.id) || [],
    [resultsData, selectedIds],
  );

  const expandedResult = resultsData?.results.find((r) => r.id === expandedId);

  const pieData = useMemo(() =>
    jobData ? Object.entries(jobData.by_category).map(([key, value]) => ({
      name: CATEGORY_CONFIG[key]?.label || key,
      value,
      color: CATEGORY_CONFIG[key]?.color || "#6B7280",
    })) : [],
    [jobData],
  );

  if (jobLoading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 bg-gray-200 rounded animate-pulse" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <div key={i} className="h-24 bg-gray-100 rounded-lg animate-pulse" />)}
        </div>
      </div>
    );
  }

  if (!jobData) return <p className="text-gray-500">Job not found</p>;

  const { job } = jobData;
  const isActive = !(TERMINAL_STATUSES as readonly string[]).includes(job.status);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to="/research" className="text-gray-400 hover:text-gray-600"><ArrowLeft size={20} /></Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900">{job.name}</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {job.total_companies} companies · {job.method}
            {job.completed_at && ` · ${new Date(job.completed_at).toLocaleDateString()}`}
          </p>
        </div>
        <div className="flex gap-2">
          {job.status === "failed" && jobData.error_count > 0 && (
            <button
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending}
              className="flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50"
            >
              <RefreshCw size={14} /> Retry {jobData.error_count} Failed
            </button>
          )}
          {isActive && (
            <button
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              className="flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              <XCircle size={14} /> Cancel
            </button>
          )}
        </div>
      </div>

      {/* Progress (active jobs only) */}
      {isActive && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <ResearchProgressBar job={job} />
          <div className="mt-3 flex items-center justify-between text-xs text-gray-500">
            <span>Cost: <span className="tabular-nums font-medium">${job.actual_cost_usd.toFixed(2)}</span> / ${job.cost_estimate_usd?.toFixed(2) || "?"}</span>
            {job.started_at && <span>Started {new Date(job.started_at).toLocaleTimeString()}</span>}
          </div>
        </div>
      )}

      {/* Completion summary */}
      {job.status === "completed" && (
        <CompletionSummary jobData={jobData} onBatchImport={() => setShowBatchImport(true)} />
      )}

      {job.error_message && (
        <div className="rounded-lg bg-red-50 border border-red-100 px-4 py-3 text-sm text-red-700">
          {job.error_message}
        </div>
      )}

      {/* Analytics row */}
      {Object.keys(jobData.by_category).length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Metric cards */}
          <div className="grid grid-cols-2 gap-3">
            <MetricCard label="Avg Score" value={String(jobData.avg_score)} accentColor="blue" />
            <MetricCard label="Confirmed" value={String(jobData.by_category.confirmed_investor || 0)} accentColor="green" />
            <MetricCard label="Likely" value={String(jobData.by_category.likely_interested || 0)} accentColor="blue" />
            <MetricCard label="Warm Intros" value={String(jobData.warm_intro_count)} accentColor="yellow" />
          </div>

          {/* Score distribution bar chart */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Score Distribution</h3>
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={jobData.score_distribution} layout="vertical">
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="range" tick={{ fontSize: 11 }} width={50} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E5E7EB" }}
                  formatter={(value: number) => [`${value} companies`, "Count"]}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {jobData.score_distribution.map((entry) => (
                    <Cell key={entry.range} fill={SCORE_COLORS[entry.range] || "#6B7280"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Category pie */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Category Breakdown</h3>
            <ResponsiveContainer width="100%" height={140}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={35}
                  outerRadius={55}
                  paddingAngle={3}
                  dataKey="value"
                >
                  {pieData.map((entry, i) => (
                    <Cell key={i} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #E5E7EB" }}
                  formatter={(value: number, name: string) => [`${value}`, name]}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex flex-wrap gap-2 justify-center mt-1">
              {pieData.map((d) => (
                <span key={d.name} className="flex items-center gap-1 text-[10px] text-gray-500">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: d.color }} />
                  {d.name}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Filters + batch actions */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={filters.category || ""}
          onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined, page: 1 })}
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Categories</option>
          {Object.entries(CATEGORY_CONFIG).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>

        <select
          value={filters.min_score ?? ""}
          onChange={(e) => setFilters({ ...filters, min_score: e.target.value ? Number(e.target.value) : undefined, page: 1 })}
          className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Min Score</option>
          <option value="80">80+ Confirmed</option>
          <option value="60">60+ Likely</option>
          <option value="40">40+ Possible</option>
        </select>

        <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={filters.has_warm_intros === true}
            onChange={(e) => setFilters({ ...filters, has_warm_intros: e.target.checked || undefined, page: 1 })}
            className="rounded border-gray-300 text-blue-600"
          />
          Warm intros
        </label>

        <div className="ml-auto flex items-center gap-2">
          {selectedIds.size > 0 && (
            <button
              onClick={() => {
                // Use selected IDs for batch import
                setShowBatchImport(true);
              }}
              className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
            >
              Import {selectedIds.size} Selected
            </button>
          )}
          {resultsData && (
            <span className="text-sm text-gray-500">{resultsData.total} results</span>
          )}
        </div>
      </div>

      {/* Expanded detail */}
      {expandedResult && (
        <div>
          <button onClick={() => setExpandedId(null)} className="text-xs text-gray-500 hover:text-gray-700 mb-2">
            Close detail
          </button>
          <ExpandedResult result={expandedResult} />
        </div>
      )}

      {/* Results table */}
      {resultsLoading ? (
        <div className="h-48 bg-gray-100 rounded-lg animate-pulse" />
      ) : resultsData && resultsData.results.length > 0 ? (
        <>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-50/80 border-b">
                <tr>
                  <th className="px-3 py-3 w-10">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === resultsData.results.length && resultsData.results.length > 0}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedIds(new Set(resultsData.results.map((r) => r.id)));
                        } else {
                          setSelectedIds(new Set());
                        }
                      }}
                      className="rounded border-gray-300 text-blue-600"
                    />
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Company</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Score</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Category</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Evidence</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Contacts</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Intro</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {resultsData.results.map((r) => (
                  <ResultRow
                    key={r.id}
                    result={r}
                    selected={selectedIds.has(r.id)}
                    onSelect={(checked) => {
                      const next = new Set(selectedIds);
                      if (checked) next.add(r.id); else next.delete(r.id);
                      setSelectedIds(next);
                    }}
                    onExpand={() => setExpandedId((prev) => prev === r.id ? null : r.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {resultsData.pages > 1 && (
            <div className="flex items-center justify-center gap-1">
              {Array.from({ length: Math.min(resultsData.pages, 10) }, (_, i) => (
                <button
                  key={i}
                  onClick={() => setFilters({ ...filters, page: i + 1 })}
                  className={`px-3 py-1.5 text-sm rounded-md ${
                    filters.page === i + 1 ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-100"
                  }`}
                >
                  {i + 1}
                </button>
              ))}
            </div>
          )}
        </>
      ) : !isActive ? (
        <p className="text-center text-gray-500 py-8">No results match filters</p>
      ) : null}

      {/* Batch import modal */}
      {showBatchImport && (
        <BatchImportModal
          jobId={jobId}
          qualifiedIds={qualifiedSelectedIds.length > 0 ? qualifiedSelectedIds : qualifiedIds}
          onClose={() => setShowBatchImport(false)}
        />
      )}
    </div>
  );
}
