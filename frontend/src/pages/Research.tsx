import { useState, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Search, Upload, Trash2, Download, X, AlertTriangle, CheckCircle, XCircle, Globe } from "lucide-react";
import { api } from "../api/client";
import type { ResearchJob, CsvPreview } from "../types";
import { TERMINAL_STATUSES } from "../types";
import ResearchProgressBar from "../components/ResearchProgressBar";
import EmptyState from "../components/EmptyState";

const STATUS_CONFIG: Record<string, { bg: string; text: string; label: string }> = {
  pending: { bg: "bg-gray-100", text: "text-gray-600", label: "Queued" },
  researching: { bg: "bg-blue-100", text: "text-blue-700", label: "Researching" },
  classifying: { bg: "bg-indigo-100", text: "text-indigo-700", label: "Classifying" },
  completed: { bg: "bg-green-100", text: "text-green-700", label: "Completed" },
  failed: { bg: "bg-red-100", text: "text-red-700", label: "Failed" },
  cancelling: { bg: "bg-amber-100", text: "text-amber-700", label: "Cancelling" },
  cancelled: { bg: "bg-gray-100", text: "text-gray-500", label: "Cancelled" },
};

const METHOD_LABELS: Record<string, string> = {
  web_search: "Web Search",
  website_crawl: "Website Crawl",
  hybrid: "Hybrid",
};

// ---------------------------------------------------------------------------
// New Job Modal with CSV Preview
// ---------------------------------------------------------------------------

function NewJobModal({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<"upload" | "preview" | "confirm">("upload");
  const [name, setName] = useState("");
  const [method, setMethod] = useState("hybrid");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();

  const costPerCompany = method === "website_crawl" ? 0.006 : 0.011;
  const estimatedCost = preview ? (preview.total_rows * costPerCompany) : 0;

  const createMutation = useMutation({
    mutationFn: () => api.createResearchJob(file!, name, method),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["research-jobs"] });
      onClose();
    },
  });

  const handleFileSelect = useCallback(async (f: File) => {
    setFile(f);
    setPreviewError("");
    setPreviewLoading(true);
    try {
      const p = await api.previewResearchCsv(f);
      setPreview(p);
      setStep("preview");
    } catch (err: any) {
      setPreviewError(err.message || "Failed to parse CSV");
    } finally {
      setPreviewLoading(false);
    }
  }, []);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f?.name.endsWith(".csv")) handleFileSelect(f);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">New Research Job</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {step === "upload" && "Upload a company list to research"}
              {step === "preview" && "Review your data before starting"}
              {step === "confirm" && "Confirm cost and begin"}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1">
            <X size={20} />
          </button>
        </div>

        {/* Step: Upload */}
        {step === "upload" && (
          <div className="px-6 py-5 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Job Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Q1 Family Office Research"
                className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Research Method</label>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { value: "hybrid", label: "Hybrid", desc: "Web + Crawl", icon: "🔍" },
                  { value: "web_search", label: "Web Search", desc: "Perplexity API", icon: "🌐" },
                  { value: "website_crawl", label: "Crawl Only", desc: "Free, less data", icon: "🕷️" },
                ].map((m) => (
                  <button
                    key={m.value}
                    onClick={() => setMethod(m.value)}
                    className={`rounded-lg border-2 p-3 text-left transition-all ${
                      method === m.value
                        ? "border-blue-500 bg-blue-50"
                        : "border-gray-100 hover:border-gray-200"
                    }`}
                  >
                    <span className="text-lg">{m.icon}</span>
                    <p className="text-sm font-medium text-gray-900 mt-1">{m.label}</p>
                    <p className="text-xs text-gray-500">{m.desc}</p>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Company List</label>
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileRef.current?.click()}
                className={`border-2 border-dashed rounded-xl px-6 py-10 text-center cursor-pointer transition-all ${
                  dragOver ? "border-blue-400 bg-blue-50 scale-[1.01]" :
                  previewLoading ? "border-blue-300 bg-blue-50/50" :
                  "border-gray-200 hover:border-gray-300 hover:bg-gray-50/50"
                }`}
              >
                <input
                  ref={fileRef}
                  type="file"
                  accept=".csv"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) handleFileSelect(f);
                  }}
                />
                {previewLoading ? (
                  <div className="space-y-2">
                    <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
                    <p className="text-sm text-blue-600">Parsing CSV...</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Upload size={28} className="mx-auto text-gray-400" />
                    <p className="text-sm font-medium text-gray-700">Drop CSV here or click to browse</p>
                    <p className="text-xs text-gray-400">
                      Required: company_name · Optional: website, country, aum, firm_type
                    </p>
                  </div>
                )}
              </div>
              {previewError && (
                <p className="mt-2 text-sm text-red-600 flex items-center gap-1.5">
                  <AlertTriangle size={14} /> {previewError}
                </p>
              )}
            </div>
          </div>
        )}

        {/* Step: Preview */}
        {step === "preview" && preview && (
          <div className="px-6 py-5 space-y-4 max-h-[60vh] overflow-y-auto">
            {/* Stats bar */}
            <div className="grid grid-cols-4 gap-3">
              <div className="rounded-lg bg-gray-50 px-3 py-2 text-center">
                <p className="text-xl font-bold text-gray-900">{preview.total_rows}</p>
                <p className="text-xs text-gray-500">Companies</p>
              </div>
              <div className="rounded-lg bg-gray-50 px-3 py-2 text-center">
                <p className="text-xl font-bold text-gray-900">{preview.stats.with_website}</p>
                <p className="text-xs text-gray-500">With Website</p>
              </div>
              <div className="rounded-lg bg-gray-50 px-3 py-2 text-center">
                <p className="text-xl font-bold text-gray-900">{preview.stats.with_aum}</p>
                <p className="text-xs text-gray-500">With AUM</p>
              </div>
              <div className="rounded-lg bg-gray-50 px-3 py-2 text-center">
                <p className="text-xl font-bold text-blue-600 tabular-nums">${estimatedCost.toFixed(2)}</p>
                <p className="text-xs text-gray-500">Est. Cost</p>
              </div>
            </div>

            {/* Column mapping */}
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">Column Mapping</p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(preview.mapped_headers).map(([raw, mapped]) => (
                  <span key={raw} className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2 py-1 text-xs">
                    <span className="text-gray-400">{raw}</span>
                    <span className="text-gray-300">→</span>
                    <span className="font-medium text-gray-700">{mapped}</span>
                  </span>
                ))}
              </div>
            </div>

            {/* Preview table */}
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">
                Preview (first {Math.min(preview.preview.length, 10)} rows)
              </p>
              <div className="rounded-lg border border-gray-200 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium text-gray-500">Company</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500">Website</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500">Country</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500">AUM</th>
                      <th className="px-3 py-2 text-left font-medium text-gray-500">Type</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {preview.preview.map((row, i) => (
                      <tr key={i} className="hover:bg-gray-50/50">
                        <td className="px-3 py-2 font-medium text-gray-900">{row.company_name}</td>
                        <td className="px-3 py-2 text-gray-500 truncate max-w-[150px]">{row.website || "—"}</td>
                        <td className="px-3 py-2 text-gray-500">{row.country || "—"}</td>
                        <td className="px-3 py-2 text-gray-500 tabular-nums">{row.aum || "—"}</td>
                        <td className="px-3 py-2 text-gray-500">{row.firm_type || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {preview.total_rows > 10 && (
                <p className="text-xs text-gray-400 mt-1 text-right">
                  +{preview.total_rows - 10} more rows
                </p>
              )}
            </div>
          </div>
        )}

        {/* Step: Confirm */}
        {step === "confirm" && preview && (
          <div className="px-6 py-8 text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-blue-50 flex items-center justify-center mx-auto">
              <Globe size={28} className="text-blue-600" />
            </div>
            <div>
              <p className="text-gray-700">
                Research <strong>{preview.total_rows}</strong> companies using <strong>{METHOD_LABELS[method]}</strong>
              </p>
              <p className="text-3xl font-bold text-gray-900 mt-2 tabular-nums">
                ~${estimatedCost.toFixed(2)}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                Perplexity sonar + Claude Haiku classification
              </p>
            </div>
            {createMutation.isError && (
              <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">
                {createMutation.error.message}
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100 bg-gray-50/50">
          <div className="text-xs text-gray-400">
            {file && `${file.name}`}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => {
                if (step === "preview") setStep("upload");
                else if (step === "confirm") setStep("preview");
                else onClose();
              }}
              className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              {step === "upload" ? "Cancel" : "Back"}
            </button>

            {step === "upload" && (
              <button
                disabled
                className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white opacity-50 cursor-not-allowed"
              >
                Upload CSV to Continue
              </button>
            )}
            {step === "preview" && (
              <button
                onClick={() => setStep("confirm")}
                disabled={!name.trim()}
                className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
              >
                {!name.trim() ? "Enter a job name first" : "Review Cost"}
              </button>
            )}
            {step === "confirm" && (
              <button
                onClick={() => createMutation.mutate()}
                disabled={createMutation.isPending}
                className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {createMutation.isPending ? "Starting..." : "Start Research"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Active Job Banner
// ---------------------------------------------------------------------------

function ActiveJobBanner({ job }: { job: ResearchJob }) {
  const queryClient = useQueryClient();
  const cancelMutation = useMutation({
    mutationFn: () => api.cancelResearchJob(job.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["research-jobs"] }),
  });

  return (
    <div className="rounded-xl bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="w-2.5 h-2.5 rounded-full bg-blue-500 animate-pulse" />
          <div>
            <Link to={`/research/${job.id}`} className="text-sm font-semibold text-gray-900 hover:text-blue-700">
              {job.name}
            </Link>
            <p className="text-xs text-gray-500">{METHOD_LABELS[job.method]} · ${job.actual_cost_usd.toFixed(2)} spent</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to={`/research/${job.id}`}
            className="rounded-lg bg-white border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            View Details
          </Link>
          <button
            onClick={() => cancelMutation.mutate()}
            disabled={cancelMutation.isPending}
            className="rounded-lg bg-white border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </div>
      <ResearchProgressBar job={job} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Job Row
// ---------------------------------------------------------------------------

function JobRow({ job }: { job: ResearchJob }) {
  const queryClient = useQueryClient();
  const deleteMutation = useMutation({
    mutationFn: () => api.deleteResearchJob(job.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["research-jobs"] }),
  });

  const status = STATUS_CONFIG[job.status] || STATUS_CONFIG.pending;
  const isTerminal = (TERMINAL_STATUSES as readonly string[]).includes(job.status);

  return (
    <tr className="hover:bg-gray-50 transition-colors group">
      <td className="px-5 py-4">
        <Link to={`/research/${job.id}`} className="text-sm font-medium text-gray-900 hover:text-blue-600 group-hover:text-blue-600">
          {job.name}
        </Link>
        <p className="text-xs text-gray-400 mt-0.5">{METHOD_LABELS[job.method]}</p>
      </td>
      <td className="px-5 py-4">
        <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${status.bg} ${status.text}`}>
          {status.label}
        </span>
      </td>
      <td className="px-5 py-4">
        <span className="text-sm tabular-nums text-gray-700">{job.total_companies}</span>
      </td>
      <td className="px-5 py-4">
        {!isTerminal ? (
          <div className="w-48"><ResearchProgressBar job={job} /></div>
        ) : (
          <div className="flex items-center gap-1.5">
            {job.status === "completed" && <CheckCircle size={14} className="text-green-500" />}
            {job.status === "failed" && <XCircle size={14} className="text-red-500" />}
            <span className="text-sm text-gray-500">
              {job.processed_companies}/{job.total_companies}
            </span>
          </div>
        )}
      </td>
      <td className="px-5 py-4 text-sm tabular-nums text-gray-600">
        ${job.actual_cost_usd.toFixed(2)}
      </td>
      <td className="px-5 py-4 text-sm text-gray-400">
        {new Date(job.created_at).toLocaleDateString()}
      </td>
      <td className="px-5 py-3">
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {job.status === "completed" && (
            <button
              onClick={(e) => { e.stopPropagation(); api.exportResearchResults(job.id); }}
              className="p-1.5 text-gray-400 hover:text-gray-600 rounded hover:bg-gray-100"
              title="Export CSV"
            >
              <Download size={15} />
            </button>
          )}
          {isTerminal && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (confirm("Delete this research job and all results?")) deleteMutation.mutate();
              }}
              className="p-1.5 text-gray-400 hover:text-red-600 rounded hover:bg-red-50"
              title="Delete"
            >
              <Trash2 size={15} />
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function Research() {
  const [showNewJob, setShowNewJob] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["research-jobs"],
    queryFn: () => api.listResearchJobs(),
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs;
      const hasActive = jobs?.some(
        (j) => !(TERMINAL_STATUSES as readonly string[]).includes(j.status)
      );
      return hasActive ? 3000 : false;
    },
  });

  const activeJob = data?.jobs.find(
    (j) => !(TERMINAL_STATUSES as readonly string[]).includes(j.status)
  );
  const completedJobs = data?.jobs.filter(
    (j) => (TERMINAL_STATUSES as readonly string[]).includes(j.status)
  ) || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Company Research</h1>
          <p className="text-sm text-gray-500 mt-1">
            Research crypto and digital asset interest across allocator lists
          </p>
        </div>
        <button
          onClick={() => setShowNewJob(true)}
          disabled={!!activeJob}
          className="flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed"
          title={activeJob ? "Wait for running job to complete" : undefined}
        >
          <Search size={16} />
          New Research Job
        </button>
      </div>

      {/* Active job banner */}
      {activeJob && <ActiveJobBanner job={activeJob} />}

      {/* Job list */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 bg-gray-100 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : !data?.jobs.length ? (
        <EmptyState
          icon={Search}
          title="No research jobs yet"
          description="Upload a company list to discover who's investing in crypto"
          action={{ label: "New Research Job", onClick: () => setShowNewJob(true) }}
        />
      ) : completedJobs.length > 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50/80 border-b">
              <tr>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Job</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Companies</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Progress</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Cost</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Date</th>
                <th className="px-5 py-3 w-20"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {completedJobs.map((job) => (
                <JobRow key={job.id} job={job} />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {showNewJob && <NewJobModal onClose={() => setShowNewJob(false)} />}
    </div>
  );
}
