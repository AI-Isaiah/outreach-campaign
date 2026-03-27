import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import ErrorBoundary from "../components/ErrorBoundary";
import { useNavigate, useLocation, useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Upload,
  FileText,
  CheckCircle,
  AlertCircle,
  Loader2,
  Info,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import {
  smartImportApi,
  type AnalyzeResult,
  type PreviewResult,
  type ImportResult,
  type RowAction,
  type RowDecision,
} from "../api/smartImport";
import { campaignsApi } from "../api/campaigns";
import PreviewTableRow from "../components/PreviewTableRow";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import Pagination from "../components/Pagination";

type Step = "upload" | "mapping" | "preview";

/** Target fields available for column mapping. */
const TARGET_FIELDS = [
  { value: "", label: "Ignore" },
  { value: "company.name", label: "Company Name" },
  { value: "company.domain", label: "Company Domain" },
  { value: "company.industry", label: "Industry" },
  { value: "company.country", label: "Country" },
  { value: "company.aum", label: "AUM" },
  { value: "company.tier", label: "Tier" },
  { value: "company.firm_type", label: "Firm Type" },
  { value: "company.website", label: "Website" },
  { value: "company.address", label: "Address" },
  { value: "contact.first_name", label: "First Name" },
  { value: "contact.last_name", label: "Last Name" },
  { value: "contact.full_name", label: "Full Name" },
  { value: "contact.email", label: "Email" },
  { value: "contact.title", label: "Title" },
  { value: "contact.linkedin_url", label: "LinkedIn URL" },
  { value: "contact.phone", label: "Phone" },
  { value: "contact.notes", label: "Notes" },
] as const;

const STEPS: { key: Step; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "mapping", label: "Map Columns" },
  { key: "preview", label: "Preview & Import" },
];

const CAMPAIGN_STEPS = ["Sequence", "Messages", "Review"];

const PREVIEW_COLUMNS = [
  { key: "company_name", label: "Company" },
  { key: "full_name", label: "Name" },
  { key: "email", label: "Email" },
  { key: "title", label: "Title" },
  { key: "country", label: "Country" },
  { key: "linkedin_url", label: "LinkedIn" },
  { key: "aum_millions", label: "AUM ($M)" },
] as const;

function confidenceColor(c: number): string {
  if (c >= 0.8) return "text-green-600 bg-green-50 border-green-200";
  if (c >= 0.5) return "text-yellow-600 bg-yellow-50 border-yellow-200";
  return "text-red-600 bg-red-50 border-red-200";
}

function confidenceLabel(c: number): string {
  if (c >= 0.8) return "High confidence";
  if (c >= 0.5) return "Medium confidence";
  return "Low confidence";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const ANALYSIS_MESSAGES = [
  "Reading CSV structure...",
  "Detecting column patterns...",
  "Matching to CRM fields...",
  "Analyzing contact layout...",
] as const;

function AnalysisStatus() {
  const [msgIndex, setMsgIndex] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setMsgIndex((i) => (i + 1) % ANALYSIS_MESSAGES.length), 2500);
    return () => clearInterval(timer);
  }, []);
  return <p className="text-sm text-gray-500">{ANALYSIS_MESSAGES[msgIndex]}</p>;
}

function SmartImportInner() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Job ID persisted in URL — survives navigation
  const [jobId, setJobId] = useState<string | null>(searchParams.get("job"));

  // Wizard state
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [analysis, setAnalysis] = useState<AnalyzeResult | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [sourceLabel, setSourceLabel] = useState("");
  const [previewData, setPreviewData] = useState<PreviewResult | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const resumeCheckedRef = useRef(false);

  // Preview table state
  const [previewPage, setPreviewPage] = useState(1);
  const [previewPageSize, setPreviewPageSize] = useState(50);
  const [previewSortBy, setPreviewSortBy] = useState<string>("");
  const [previewSortDir, setPreviewSortDir] = useState<"asc" | "desc">("asc");
  const [previewFilter, setPreviewFilter] = useState("");
  const debouncedPreviewFilter = useDebouncedValue(previewFilter, 300);
  const [previewShowFilter, setPreviewShowFilter] = useState<"all" | "new" | "matches" | "file_dupes">("all");
  const [excludedIndices, setExcludedIndices] = useState<Set<number>>(new Set());
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());
  const [expandedDuplicate, setExpandedDuplicate] = useState<number | null>(null);
  const [rowDecisions, setRowDecisions] = useState<Record<number, RowDecision>>({});
  const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(null);

  // Accept file from ImportWizard navigation state
  const location = useLocation();
  const locationStateFile = (location.state as { file?: File } | null)?.file ?? null;

  // --- Helper: apply analysis result from server to local state ---
  const applyAnalysisResult = useCallback(
    (id: string, result: Omit<AnalyzeResult, "import_job_id">) => {
      const fullAnalysis: AnalyzeResult = { import_job_id: id, ...result };
      setAnalysis(fullAnalysis);
      const fullMapping: Record<string, string> = {};
      for (const h of result.headers ?? []) {
        fullMapping[h] = result.proposed_mapping[h] || "";
      }
      setMapping(fullMapping);
      setStep("mapping");
    },
    [], // all deps are stable state setters
  );

  // --- Persist jobId in URL ---
  useEffect(() => {
    if (jobId && searchParams.get("job") !== jobId) {
      setSearchParams({ job: jobId }, { replace: true });
    }
  }, [jobId, searchParams, setSearchParams]);

  // --- Poll for analysis completion when job is analyzing ---
  const isAnalyzingInBackground = step === "upload" && !!jobId && !analysis;
  const pollingJobId = isAnalyzingInBackground ? jobId : undefined;
  const jobPollQuery = useQuery({
    queryKey: ["import-job", pollingJobId],
    queryFn: () => smartImportApi.getJob(pollingJobId!),
    enabled: isAnalyzingInBackground,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "analyzing" ? 2000 : false;
    },
  });

  // When polling detects analysis complete, apply the result
  useEffect(() => {
    if (!jobPollQuery.data || !jobId) return;
    const job = jobPollQuery.data;
    if (job.status === "pending" && job.analysis_result) {
      applyAnalysisResult(jobId, job.analysis_result);
    } else if (job.status === "failed") {
      setStep("upload");
      setJobId(null);
    }
  }, [jobPollQuery.data, jobId, applyAnalysisResult]);

  // --- Resume: on mount, check URL job param or active job ---
  useEffect(() => {
    if (resumeCheckedRef.current) return;
    resumeCheckedRef.current = true;
    let cancelled = false;

    const urlJobId = searchParams.get("job");

    const resumeJob = (id: string, job: { status: string; analysis_result?: unknown; column_mapping?: Record<string, string> | null }) => {
      if (cancelled) return;
      setJobId(id);
      if ((job.status === "pending" || job.status === "previewed") && job.analysis_result) {
        const result = job.analysis_result as Omit<AnalyzeResult, "import_job_id">;
        // If user already approved a mapping (previewed), use that instead of the LLM proposal
        if (job.status === "previewed" && job.column_mapping) {
          const fullAnalysis: AnalyzeResult = { import_job_id: id, ...result };
          setAnalysis(fullAnalysis);
          setMapping(job.column_mapping);
          setStep("mapping");
        } else {
          applyAnalysisResult(id, result);
        }
      }
      // If analyzing, polling will handle the rest
    };

    if (urlJobId) {
      smartImportApi.getJob(urlJobId).then((job) => {
        resumeJob(urlJobId, job);
      }).catch(() => {
        if (!cancelled) setJobId(null);
      });
    } else {
      smartImportApi.getActiveJob().then((job) => {
        if (cancelled || !job) return;
        resumeJob(job.id, job);
      }).catch(() => {});
    }

    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps — mount-only

  // Campaigns for enrollment selector
  const campaignsQuery = useQuery({
    queryKey: ["campaigns"],
    queryFn: campaignsApi.listCampaigns,
    enabled: step === "preview",
  });

  const handleRowDecision = (index: number, action: RowAction, existingContactId?: number) => {
    setRowDecisions((prev) => ({
      ...prev,
      [index]: { action, existing_contact_id: existingContactId },
    }));
    // Auto-advance: collapse current row, expand next match
    const matchRows = paginatedPreviewRows.filter(
      (r) => r.existing_contact_id && r._index !== index && !rowDecisions[r._index]
    );
    if (matchRows.length > 0) {
      setExpandedDuplicate(matchRows[0]._index);
    } else {
      setExpandedDuplicate(null);
    }
  };

  // Mutations
  const analyzeMutation = useMutation({
    mutationFn: (f: File) => smartImportApi.analyze(f),
    onSuccess: (data) => {
      // Async: store jobId, polling handles the rest
      setJobId(data.import_job_id);
    },
  });

  useEffect(() => {
    if (locationStateFile && !file) {
      setFile(locationStateFile);
      analyzeMutation.mutate(locationStateFile);
    }
  }, [locationStateFile]); // eslint-disable-line react-hooks/exhaustive-deps

  const previewMutation = useMutation({
    mutationFn: () =>
      smartImportApi.preview(
        jobId!,
        mapping,
        sourceLabel || undefined,
      ),
    onSuccess: (data) => {
      setPreviewData(data);
      setStep("preview");
    },
  });

  const executeMutation = useMutation({
    mutationFn: () =>
      smartImportApi.execute(
        jobId!,
        excludedIndices.size > 0 ? [...excludedIndices] : undefined,
        Object.keys(rowDecisions).length > 0 ? rowDecisions : undefined,
        selectedCampaignId ?? undefined,
      ),
    onSuccess: (data) => {
      setImportResult(data);
    },
  });

  // Handlers
  const handleFile = useCallback((f: File) => {
    if (!f.name.endsWith(".csv")) return;
    setFile(f);
    setAnalysis(null);
    setPreviewData(null);
    setImportResult(null);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const f = e.dataTransfer.files[0];
      if (f) handleFile(f);
    },
    [handleFile],
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (f) handleFile(f);
      e.target.value = "";
    },
    [handleFile],
  );

  const handleAnalyze = () => {
    if (file) analyzeMutation.mutate(file);
  };

  const handleMappingChange = (csvCol: string, target: string) => {
    setMapping((prev) => ({ ...prev, [csvCol]: target }));
  };

  const resetAll = () => {
    setStep("upload");
    setFile(null);
    setJobId(null);
    setAnalysis(null);
    setMapping({});
    setSourceLabel("");
    setPreviewData(null);
    setImportResult(null);
    setPreviewPage(1);
    setPreviewPageSize(50);
    setPreviewSortBy("");
    setPreviewSortDir("asc");
    setPreviewFilter("");
    setPreviewShowFilter("all");
    setExcludedIndices(new Set());
    setSelectedIndices(new Set());
    setExpandedDuplicate(null);
    setRowDecisions({});
    setSelectedCampaignId(null);
    analyzeMutation.reset();
    previewMutation.reset();
    executeMutation.reset();
    setSearchParams({}, { replace: true });
  };

  // Derived
  const stepIndex = STEPS.findIndex((s) => s.key === step);

  // Filtered, sorted, paginated preview rows
  const filteredPreviewRows = useMemo(() => {
    if (!previewData) return [];
    let rows = previewData.preview_rows;

    // Status filter (V2: tier-based)
    if (previewShowFilter === "new")
      rows = rows.filter((r) => r.resolution_tier === "new" || r.resolution_tier === "auto_merge");
    else if (previewShowFilter === "matches")
      rows = rows.filter((r) => r.resolution_tier === "review" || r.resolution_tier === "company_change");
    else if (previewShowFilter === "file_dupes")
      rows = rows.filter((r) => r.resolution_tier === "file_duplicate");

    // Text search
    if (debouncedPreviewFilter.trim()) {
      const q = debouncedPreviewFilter.toLowerCase();
      rows = rows.filter((r) =>
        PREVIEW_COLUMNS.some((col) => {
          const val = r[col.key];
          return val != null && String(val).toLowerCase().includes(q);
        }),
      );
    }

    // Sort
    if (previewSortBy) {
      const dir = previewSortDir === "asc" ? 1 : -1;
      rows = [...rows].sort((a, b) => {
        const av = a[previewSortBy] ?? "";
        const bv = b[previewSortBy] ?? "";
        if (typeof av === "number" && typeof bv === "number")
          return (av - bv) * dir;
        return String(av).localeCompare(String(bv)) * dir;
      });
    }

    return rows;
  }, [previewData, debouncedPreviewFilter, previewShowFilter, previewSortBy, previewSortDir]);

  const previewTotalPages = useMemo(() => {
    if (previewPageSize === Infinity) return 1;
    return Math.max(1, Math.ceil(filteredPreviewRows.length / previewPageSize));
  }, [filteredPreviewRows.length, previewPageSize]);

  const paginatedPreviewRows = useMemo(() => {
    if (previewPageSize === Infinity) return filteredPreviewRows;
    const start = (previewPage - 1) * previewPageSize;
    return filteredPreviewRows.slice(start, start + previewPageSize);
  }, [filteredPreviewRows, previewPage, previewPageSize]);

  // Triage summary from backend (V2)
  const triage = previewData?.triage_summary ?? null;

  // Effective counts with decisions
  const effectiveCounts = useMemo(() => {
    if (!previewData) return { toImport: 0, toMerge: 0, toEnroll: 0, toSkip: 0, matches: 0, fileDupes: 0 };
    let toImport = 0, toMerge = 0, toEnroll = 0, toSkip = 0, matches = 0, fileDupes = 0;
    for (const r of previewData.preview_rows) {
      if (excludedIndices.has(r._index)) { toSkip++; continue; }
      if (r.within_file_duplicate) { fileDupes++; continue; }
      const decision = rowDecisions[r._index];
      if (decision) {
        if (decision.action === "merge") toMerge++;
        else if (decision.action === "enroll") toEnroll++;
        else if (decision.action === "skip") toSkip++;
        else toImport++;
      } else if (r.match_type) {
        matches++;
      } else {
        toImport++;
      }
    }
    return { toImport, toMerge, toEnroll, toSkip, matches, fileDupes };
  }, [previewData, excludedIndices, rowDecisions]);

  const handlePreviewSort = (key: string) => {
    if (previewSortBy === key) {
      setPreviewSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setPreviewSortBy(key);
      setPreviewSortDir("asc");
    }
    setPreviewPage(1);
  };

  const toggleExcluded = (idx: number) => {
    setExcludedIndices((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleSelected = (idx: number) => {
    setSelectedIndices((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIndices.size === paginatedPreviewRows.length) {
      setSelectedIndices(new Set());
    } else {
      setSelectedIndices(new Set(paginatedPreviewRows.map((r) => r._index)));
    }
  };

  const bulkExclude = () => {
    setExcludedIndices((prev) => {
      const next = new Set(prev);
      selectedIndices.forEach((idx) => next.add(idx));
      return next;
    });
    setSelectedIndices(new Set());
  };

  const bulkInclude = () => {
    setExcludedIndices((prev) => {
      const next = new Set(prev);
      selectedIndices.forEach((idx) => next.delete(idx));
      return next;
    });
    setSelectedIndices(new Set());
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <button
          onClick={() => navigate("/contacts")}
          className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
        >
          &larr; Contacts
        </button>
        <h1 className="text-2xl font-bold text-gray-900 mt-2">
          Smart Import
        </h1>
        <p className="text-gray-500 mt-1">
          AI-powered column detection and mapping for any CSV layout
        </p>
      </div>

      {/* Step indicator — import + campaign flow */}
      <div className="flex items-center gap-3 text-sm flex-wrap">
        {STEPS.map((s, i) => {
          const isCompleted = i < stepIndex;
          const isCurrent = step === s.key;
          const canNavigate = isCompleted && !importResult;
          return (
            <div key={s.key} className="flex items-center gap-2">
              <button
                disabled={!canNavigate}
                onClick={() => canNavigate && setStep(s.key)}
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium transition-colors ${
                  isCurrent
                    ? "bg-gray-900 text-white"
                    : isCompleted
                      ? "bg-green-600 text-white hover:bg-green-700 cursor-pointer"
                      : "bg-gray-200 text-gray-500"
                } ${canNavigate ? "" : "cursor-default"}`}
              >
                {isCompleted ? "\u2713" : i + 1}
              </button>
              <span
                className={`${
                  isCurrent ? "font-medium text-gray-900" : "text-gray-500"
                } ${canNavigate ? "cursor-pointer hover:text-gray-700" : ""}`}
                onClick={() => canNavigate && setStep(s.key)}
              >
                {s.label}
              </span>
              <span className="text-gray-300 mx-1">/</span>
            </div>
          );
        })}
        {CAMPAIGN_STEPS.map((label, i) => (
          <div key={label} className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium bg-gray-100 text-gray-400">
              {STEPS.length + i + 1}
            </span>
            <span className="text-gray-400">{label}</span>
            {i < CAMPAIGN_STEPS.length - 1 && (
              <span className="text-gray-300 mx-1">/</span>
            )}
          </div>
        ))}
      </div>

      {/* Step 1: Upload */}
      {step === "upload" && (
        <div className="space-y-4">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleInputChange}
            className="hidden"
          />
          {/* Drop zone — only when no file is loaded and not analyzing */}
          {!file && !analyzeMutation.isPending && !isAnalyzingInBackground && (
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
                dragOver
                  ? "border-blue-400 bg-blue-50"
                  : "border-gray-200 bg-white"
              }`}
            >
              <Upload className="mx-auto text-gray-300 mb-4" size={48} />
              <p className="text-gray-600 font-medium mb-1">
                Drag and drop your CSV file here
              </p>
              <p className="text-sm text-gray-400 mb-4">or click to browse</p>
              <button
                onClick={() => fileInputRef.current?.click()}
                className="px-4 py-2.5 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors"
              >
                Choose File
              </button>
            </div>
          )}

          {/* File loaded, ready to analyze */}
          {file && !analyzeMutation.isPending && !isAnalyzingInBackground && (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <FileText size={20} className="text-gray-400" />
                <div>
                  <p className="text-sm font-medium text-gray-900">
                    {file.name}
                  </p>
                  <p className="text-xs text-gray-500">
                    {formatBytes(file.size)}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleAnalyze}
                  className="px-4 py-2.5 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors"
                >
                  Analyze
                </button>
                <button
                  onClick={() => {
                    setFile(null);
                    setAnalysis(null);
                    analyzeMutation.reset();
                  }}
                  className="p-2 text-gray-300 hover:text-gray-500 transition-colors rounded-lg hover:bg-gray-50"
                  title="Remove file"
                >
                  <X size={16} />
                </button>
              </div>
            </div>
          )}

          {/* Animated progress bar during LLM analysis (upload in flight OR polling background job) */}
          {(analyzeMutation.isPending || isAnalyzingInBackground) && (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 space-y-4">
              <div className="flex items-center gap-3">
                <FileText size={20} className="text-gray-400" />
                <div>
                  <p className="text-sm font-medium text-gray-900">
                    {file?.name ?? jobPollQuery.data?.filename ?? "CSV file"}
                  </p>
                  {file && (
                    <p className="text-xs text-gray-500">{formatBytes(file.size)}</p>
                  )}
                </div>
              </div>
              <div className="space-y-2">
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full bg-gray-900 rounded-full animate-progress-bar" />
                </div>
                <AnalysisStatus />
                {isAnalyzingInBackground && !analyzeMutation.isPending && (
                  <p className="text-xs text-gray-400">
                    Analysis running in background — you can navigate away safely
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Note about AI analysis */}
          {file && !analyzeMutation.isPending && !isAnalyzingInBackground && (
            <p className="text-xs text-gray-400 flex items-center gap-1.5">
              <Info size={12} className="shrink-0" />
              Sample rows are sent to AI for column detection
            </p>
          )}

          {/* Analyze error */}
          {analyzeMutation.isError && (
            <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg p-4">
              <AlertCircle
                size={20}
                className="text-red-600 shrink-0 mt-0.5"
              />
              <div className="flex-1">
                <p className="text-sm font-medium text-red-800">
                  AI mapping unavailable
                </p>
                <p className="text-sm text-red-700 mt-1">
                  {(analyzeMutation.error as Error).message ||
                    "Please check your file format."}
                </p>
              </div>
              <button
                onClick={handleAnalyze}
                className="text-red-600 hover:text-red-800 shrink-0"
                title="Retry"
              >
                <RotateCcw size={16} />
              </button>
            </div>
          )}
        </div>
      )}

      {/* Step 2: Column Mapping */}
      {step === "mapping" && analysis && (
        <div className="space-y-4">
          {/* Confidence badge */}
          <div
            className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full border text-sm font-medium ${confidenceColor(analysis.confidence)}`}
          >
            {confidenceLabel(analysis.confidence)} &mdash;{" "}
            {Math.round(analysis.confidence * 100)}% match
          </div>

          {/* Row count */}
          <p className="text-sm text-gray-500">
            {analysis.row_count} row{analysis.row_count !== 1 ? "s" : ""}{" "}
            detected in file
          </p>

          {/* Multi-contact info */}
          {analysis.multi_contact.detected &&
            analysis.multi_contact.contact_groups && (
              <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-lg p-4">
                <Info size={20} className="text-blue-600 shrink-0 mt-0.5" />
                <p className="text-sm text-blue-800">
                  Detected {analysis.multi_contact.contact_groups.length}{" "}
                  contact slots per row &mdash; each will become a separate
                  contact
                </p>
              </div>
            )}

          {/* Mapping table */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    CSV Column
                  </th>
                  <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Sample Value
                  </th>
                  <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Maps To
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {Object.keys(mapping).map((csvCol) => {
                  const sampleValue =
                    analysis.sample_rows[0]?.[csvCol] ?? "";
                  return (
                    <tr key={csvCol} className="hover:bg-gray-50 transition-colors">
                      <td className="px-5 py-4 text-sm font-medium text-gray-900">
                        {csvCol}
                      </td>
                      <td
                        className="px-5 py-4 text-sm text-gray-500 max-w-[280px] truncate cursor-default"
                        title={sampleValue || undefined}
                      >
                        {sampleValue || (
                          <span className="text-gray-300">&mdash;</span>
                        )}
                      </td>
                      <td className="px-5 py-4">
                        <select
                          value={mapping[csvCol] || ""}
                          onChange={(e) =>
                            handleMappingChange(csvCol, e.target.value)
                          }
                          className="w-full text-sm border border-gray-200 rounded-md px-2.5 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
                        >
                          {TARGET_FIELDS.map((f) => (
                            <option key={f.value} value={f.value}>
                              {f.label}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Source label */}
          <div>
            <label
              htmlFor="source-label"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Source label{" "}
              <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              id="source-label"
              type="text"
              value={sourceLabel}
              onChange={(e) => setSourceLabel(e.target.value)}
              placeholder="e.g. ConferencX attendees, LinkedIn export"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
            />
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={() => previewMutation.mutate()}
              disabled={previewMutation.isPending}
              className="px-4 py-2.5 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 disabled:opacity-50 transition-colors flex items-center gap-2"
            >
              {previewMutation.isPending ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Generating preview...
                </>
              ) : (
                "Preview Import"
              )}
            </button>
            <button
              onClick={() => {
                setStep("upload");
                setAnalysis(null);
                analyzeMutation.reset();
              }}
              className="px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              Back
            </button>
          </div>

          {/* Preview error */}
          {previewMutation.isError && (
            <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg p-4">
              <AlertCircle
                size={20}
                className="text-red-600 shrink-0 mt-0.5"
              />
              <div className="flex-1">
                <p className="text-sm font-medium text-red-800">
                  Preview failed
                </p>
                <p className="text-sm text-red-700 mt-1">
                  {(previewMutation.error as Error).message}
                </p>
              </div>
              <button
                onClick={() => previewMutation.mutate()}
                className="text-red-600 hover:text-red-800 shrink-0"
                title="Retry"
              >
                <RotateCcw size={16} />
              </button>
            </div>
          )}
        </div>
      )}

      {/* Step 3: Preview & Confirm */}
      {step === "preview" && previewData && !importResult && (
        <div className="space-y-4">
          {/* Triage tab navigation (merged stats + tabs) */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden" role="tablist">
            <div className="grid grid-cols-2 md:grid-cols-4">
              {([
                { key: "new" as const, label: "Import", count: triage?.new_contacts ?? effectiveCounts.toImport, sub: `+ ${triage?.auto_mergeable ?? 0} auto-merge`, color: "green", activeColor: "ring-green-400" },
                { key: "matches" as const, label: "Review", count: triage?.needs_review ?? 0, sub: triage?.company_changes ? `${triage.company_changes} moved firms` : "conflicts", color: "amber", activeColor: "ring-amber-400" },
                { key: "file_dupes" as const, label: "File Dupes", count: triage?.file_duplicates ?? 0, sub: "in CSV", color: "purple", activeColor: "ring-purple-400" },
                { key: "all" as const, label: "All", count: previewData.total_contacts, sub: `${previewData.total_companies} companies`, color: "blue", activeColor: "ring-blue-400" },
              ] as const).map((tab) => (
                <button
                  key={tab.key}
                  role="tab"
                  aria-selected={previewShowFilter === tab.key}
                  onClick={() => setPreviewShowFilter((f) => f === tab.key ? "all" : tab.key)}
                  className={`p-4 text-left border-b-2 transition-colors hover:bg-gray-50 ${
                    previewShowFilter === tab.key
                      ? `border-${tab.color}-600 bg-${tab.color}-50/50`
                      : "border-transparent"
                  }`}
                >
                  <p className={`text-2xl font-bold ${previewShowFilter === tab.key ? `text-${tab.color}-700` : "text-gray-900"}`}>
                    {tab.count}
                  </p>
                  <p className="text-sm font-medium text-gray-500">{tab.label}</p>
                  <p className="text-xs text-gray-400">{tab.sub}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Auto-merge summary (shown on Import tab) */}
          {(previewShowFilter === "new" || previewShowFilter === "all") && triage && triage.auto_mergeable > 0 && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-blue-800">
                  {triage.auto_mergeable} contacts will be auto-merged (no conflicts)
                </p>
                <p className="text-xs text-blue-600 mt-0.5">
                  Matching LinkedIn + same email + same company — empty fields filled automatically
                </p>
              </div>
            </div>
          )}

          {/* Campaign enrollment selector */}
          <div className="flex items-center gap-3 bg-white rounded-lg border border-gray-200 p-4">
            <label htmlFor="campaign-select" className="text-sm font-medium text-gray-700 whitespace-nowrap">
              Enroll in campaign:
            </label>
            <select
              id="campaign-select"
              value={selectedCampaignId ?? ""}
              onChange={(e) => setSelectedCampaignId(e.target.value ? Number(e.target.value) : null)}
              className="flex-1 border border-gray-200 rounded-md px-2.5 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
            >
              <option value="">No campaign (import only)</option>
              {campaignsQuery.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.contacts_count} contacts)
                </option>
              ))}
            </select>
          </div>

          {excludedIndices.size > 0 && (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Info size={14} className="shrink-0" />
              {excludedIndices.size} row{excludedIndices.size !== 1 ? "s" : ""} excluded
              <button
                onClick={() => setExcludedIndices(new Set())}
                className="text-blue-600 hover:text-blue-800 underline"
              >
                Reset
              </button>
            </div>
          )}

          {/* Toolbar: search + status filter + bulk ops */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[200px]">
              <Search
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
              />
              <input
                type="text"
                value={previewFilter}
                onChange={(e) => {
                  setPreviewFilter(e.target.value);
                  setPreviewPage(1);
                }}
                placeholder="Search contacts..."
                className="w-full pl-9 pr-8 py-2 border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
              />
              {previewFilter && (
                <button
                  onClick={() => {
                    setPreviewFilter("");
                    setPreviewPage(1);
                  }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            <div className="flex items-center bg-white border border-gray-200 rounded-lg overflow-hidden text-sm">
              {(["all", "new", "matches", "file_dupes"] as const).map((f) => {
                const totalMatches = effectiveCounts.matches + effectiveCounts.toMerge + effectiveCounts.toEnroll;
                const label = f === "all" ? "All"
                  : f === "new" ? "New"
                  : f === "matches" ? `Matches (${totalMatches})`
                  : `File Dupes (${effectiveCounts.fileDupes})`;
                if (f === "file_dupes" && effectiveCounts.fileDupes === 0) return null;
                return (
                  <button
                    key={f}
                    onClick={() => {
                      setPreviewShowFilter(f);
                      setPreviewPage(1);
                    }}
                    className={`px-3 py-2 transition-colors ${
                      previewShowFilter === f
                        ? "bg-gray-900 text-white"
                        : "text-gray-600 hover:bg-gray-50"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>

            {/* Bulk match actions */}
            {(effectiveCounts.matches + effectiveCounts.toMerge + effectiveCounts.toEnroll) > 0 && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-gray-400">|</span>
                <button
                  onClick={() => {
                    const decisions: Record<number, RowDecision> = {};
                    previewData.preview_rows.forEach((r) => {
                      if (r.match_type && r.existing_contact_id) {
                        decisions[r._index] = { action: "merge", existing_contact_id: r.existing_contact_id };
                      }
                    });
                    setRowDecisions((prev) => ({ ...prev, ...decisions }));
                  }}
                  className="px-2.5 py-1.5 bg-blue-50 text-blue-700 border border-blue-200 rounded-md hover:bg-blue-100 text-xs font-medium transition-colors"
                >
                  Merge All Matches
                </button>
                <button
                  onClick={() => {
                    const decisions: Record<number, RowDecision> = {};
                    previewData.preview_rows.forEach((r) => {
                      if (r.match_type) {
                        decisions[r._index] = { action: "skip" };
                      }
                    });
                    setRowDecisions((prev) => ({ ...prev, ...decisions }));
                  }}
                  className="px-2.5 py-1.5 bg-white text-gray-600 border border-gray-200 rounded-md hover:bg-gray-50 text-xs font-medium transition-colors"
                >
                  Skip All Matches
                </button>
              </div>
            )}
          </div>

          {/* Preview table */}
          <div className="bg-white rounded-lg border border-gray-200 overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-3 py-3 w-10 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Import
                  </th>
                  <th className="px-3 py-3 w-10 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Status
                  </th>
                  {PREVIEW_COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      onClick={() => handlePreviewSort(col.key)}
                      className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-gray-700"
                    >
                      <span className="inline-flex items-center gap-1">
                        {col.label}
                        {previewSortBy === col.key && (
                          <span className="text-gray-400">
                            {previewSortDir === "asc" ? "\u25B2" : "\u25BC"}
                          </span>
                        )}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {paginatedPreviewRows.map((row) => {
                  const isExcluded = excludedIndices.has(row._index);
                  const isSelected = selectedIndices.has(row._index);
                  const isExpanded = expandedDuplicate === row._index;

                  return (
                    <PreviewTableRow
                      key={row._index}
                      row={row}
                      columns={PREVIEW_COLUMNS}
                      isExcluded={isExcluded}
                      isSelected={isSelected}
                      isExpanded={isExpanded}
                      decision={rowDecisions[row._index]}
                      onToggleExclude={() => toggleExcluded(row._index)}
                      onToggleSelect={() => toggleSelected(row._index)}
                      onToggleExpand={() =>
                        setExpandedDuplicate(isExpanded ? null : row._index)
                      }
                      onDecision={(action: RowAction) =>
                        handleRowDecision(row._index, action, row.existing_contact_id ?? undefined)
                      }
                    />
                  );
                })}
                {paginatedPreviewRows.length === 0 && (
                  <tr>
                    <td
                      colSpan={PREVIEW_COLUMNS.length + 2}
                      className="px-5 py-8 text-center text-sm text-gray-400"
                    >
                      No contacts match your filters
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <Pagination
            page={previewPage}
            totalPages={previewTotalPages}
            onPageChange={setPreviewPage}
            totalItems={filteredPreviewRows.length}
            pageSize={previewPageSize}
            onPageSizeChange={(size) => {
              setPreviewPageSize(size);
              setPreviewPage(1);
            }}
          />

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={() => executeMutation.mutate()}
              disabled={executeMutation.isPending}
              className="px-4 py-2.5 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 disabled:opacity-50 transition-colors flex items-center gap-2"
            >
              {executeMutation.isPending ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Importing...
                </>
              ) : (
                `Import ${effectiveCounts.toImport} New${triage?.auto_mergeable ? ` + Auto-merge ${triage.auto_mergeable}` : ""}${effectiveCounts.toMerge ? ` + Merge ${effectiveCounts.toMerge}` : ""}${effectiveCounts.toEnroll ? ` + Enroll ${effectiveCounts.toEnroll}` : ""}`
              )}
            </button>
            <button
              onClick={() => {
                setStep("mapping");
                setPreviewData(null);
                setExcludedIndices(new Set());
                setSelectedIndices(new Set());
                setExpandedDuplicate(null);
                previewMutation.reset();
              }}
              className="px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              Back to Mapping
            </button>
          </div>

          {/* Execute error */}
          {executeMutation.isError && (
            <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg p-4">
              <AlertCircle
                size={20}
                className="text-red-600 shrink-0 mt-0.5"
              />
              <div className="flex-1">
                <p className="text-sm font-medium text-red-800">
                  Import failed
                </p>
                <p className="text-sm text-red-700 mt-1">
                  {(executeMutation.error as Error).message}
                </p>
              </div>
              <button
                onClick={() => executeMutation.mutate()}
                className="text-red-600 hover:text-red-800 shrink-0"
                title="Retry"
              >
                <RotateCcw size={16} />
              </button>
            </div>
          )}
        </div>
      )}

      {/* Success state */}
      {importResult && (
        <div className="bg-white rounded-lg border border-gray-200 p-6 space-y-4">
          <div className="flex items-center gap-3 text-green-600">
            <CheckCircle size={24} />
            <h3 className="text-lg font-semibold">Import Complete</h3>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="bg-green-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-green-700">
                {importResult.contacts_created}
              </p>
              <p className="text-sm text-green-600">Created</p>
            </div>
            <div className="bg-blue-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-blue-700">
                {importResult.contacts_merged || 0}
              </p>
              <p className="text-sm text-blue-600">Merged</p>
            </div>
            <div className="bg-indigo-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-indigo-700">
                {importResult.contacts_enrolled || 0}
              </p>
              <p className="text-sm text-indigo-600">Enrolled</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-gray-700">
                {importResult.companies_created}
              </p>
              <p className="text-sm text-gray-600">Companies</p>
            </div>
            <div className="bg-yellow-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-yellow-700">
                {importResult.duplicates_skipped}
              </p>
              <p className="text-sm text-yellow-600">Skipped</p>
            </div>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              onClick={() => {
                const allContactIds = importResult.contact_ids ?? [];
                const totalForCampaign = importResult.contacts_created
                  + (importResult.contacts_merged || 0)
                  + (importResult.contacts_enrolled || 0)
                  + (importResult.duplicates_skipped || 0);
                navigate("/campaigns/new", {
                  state: {
                    importedContactIds: allContactIds,
                    importedCount: totalForCampaign,
                  },
                });
              }}
              className="px-6 py-2.5 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors"
            >
              Create Campaign with All {
                importResult.contacts_created
                + (importResult.contacts_merged || 0)
                + (importResult.contacts_enrolled || 0)
                + (importResult.duplicates_skipped || 0)
              } Contacts
            </button>
            <button
              onClick={() => navigate("/contacts")}
              className="px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              View Contacts
            </button>
            <button
              onClick={resetAll}
              className="px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              Import More
            </button>
            <button
              onClick={() => navigate(-1)}
              className="px-4 py-2.5 text-gray-500 text-sm font-medium hover:text-gray-700 transition-colors"
            >
              &larr; Back
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SmartImport() {
  return (
    <ErrorBoundary>
      <SmartImportInner />
    </ErrorBoundary>
  );
}
