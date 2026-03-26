import { useState, useMemo } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw, XCircle } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, PieChart, Pie } from "recharts";
import { api } from "../api/client";
import type { ResearchResult, ResearchJobDetail as ResearchJobDetailType, Campaign } from "../types";
import { isTerminalStatus } from "../types";
import ResearchProgressBar from "../components/ResearchProgressBar";
import MetricCard from "../components/MetricCard";
import CompletionSummary from "../components/research/CompletionSummary";
import BatchImportModal from "../components/research/BatchImportModal";
import { CATEGORY_CONFIG, ResultRow, ExpandedResult } from "../components/research/ResultsGrid";

const SCORE_COLORS: Record<string, string> = {
  "80-100": "#16A34A",
  "60-79": "#2563EB",
  "40-59": "#D97706",
  "20-39": "#6B7280",
  "0-19": "#DC2626",
};

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
      return status && !isTerminalStatus(status) ? 3000 : false;
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
  const isActive = !isTerminalStatus(job.status);

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
            <MetricCard label="Avg Score" value={String(jobData.avg_score)} accent="blue" />
            <MetricCard label="Confirmed" value={String(jobData.by_category.confirmed_investor || 0)} accent="green" />
            <MetricCard label="Likely" value={String(jobData.by_category.likely_interested || 0)} accent="blue" />
            <MetricCard label="Warm Intros" value={String(jobData.warm_intro_count)} accent="yellow" />
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
                  formatter={(value) => [`${value} companies`, "Count"]}
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
                  formatter={(value, name) => [`${value}`, String(name)]}
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
