import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  Upload,
  FileText,
  CheckCircle,
  AlertCircle,
  Loader2,
  Info,
  RotateCcw,
  Search,
  ChevronDown,
  ChevronRight,
  X,
} from "lucide-react";
import {
  smartImportApi,
  type AnalyzeResult,
  type PreviewResult,
  type PreviewRow,
  type ImportResult,
} from "../api/smartImport";
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

function AnalysisStatus() {
  const [msgIndex, setMsgIndex] = useState(0);
  const messages = [
    "Reading CSV structure...",
    "Detecting column patterns...",
    "Matching to CRM fields...",
    "Analyzing contact layout...",
  ];
  useEffect(() => {
    const timer = setInterval(() => setMsgIndex((i) => (i + 1) % messages.length), 2500);
    return () => clearInterval(timer);
  }, []);
  return <p className="text-sm text-gray-500">{messages[msgIndex]}</p>;
}

/** Single row in the preview table with optional duplicate expansion. */
function PreviewTableRow({
  row,
  columns,
  isExcluded,
  isSelected,
  isExpanded,
  onToggleExclude,
  onToggleSelect,
  onToggleExpand,
}: {
  row: PreviewRow;
  columns: { key: string; label: string }[];
  isExcluded: boolean;
  isSelected: boolean;
  isExpanded: boolean;
  onToggleExclude: () => void;
  onToggleSelect: () => void;
  onToggleExpand: () => void;
}) {
  const rowOpacity = isExcluded ? "opacity-40" : "";

  return (
    <>
      <tr
        className={`hover:bg-gray-50 transition-colors ${rowOpacity} ${
          row.is_duplicate ? "bg-yellow-50/50" : ""
        }`}
      >
        {/* Select checkbox */}
        <td className="px-3 py-3">
          <input
            type="checkbox"
            checked={isSelected}
            onChange={onToggleSelect}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
        </td>
        {/* Import toggle */}
        <td className="px-3 py-3 text-center">
          <input
            type="checkbox"
            checked={!isExcluded}
            onChange={onToggleExclude}
            className="rounded border-gray-300 text-green-600 focus:ring-green-500"
          />
        </td>
        {/* Status */}
        <td className="px-3 py-3">
          {row.is_duplicate ? (
            <button
              onClick={onToggleExpand}
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800 hover:bg-yellow-200 transition-colors"
            >
              {isExpanded ? (
                <ChevronDown size={12} />
              ) : (
                <ChevronRight size={12} />
              )}
              Already in CRM
            </button>
          ) : row.overlap_cleared ? (
            <span className="inline-block rounded-full px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700">
              {row.overlap_cleared === "email"
                ? "Email cleared"
                : row.overlap_cleared === "linkedin"
                  ? "LinkedIn cleared"
                  : row.overlap_cleared === "email+linkedin"
                    ? "Both cleared"
                    : "Overlap"}
            </span>
          ) : (
            <span className="inline-block rounded-full px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700">
              New
            </span>
          )}
        </td>
        {/* Data columns */}
        {columns.map((col) => {
          const val = row[col.key];
          return (
            <td
              key={col.key}
              className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap max-w-[200px] truncate"
              title={val != null ? String(val) : undefined}
            >
              {val != null && val !== "" ? (
                String(val)
              ) : (
                <span className="text-gray-300">&mdash;</span>
              )}
            </td>
          );
        })}
      </tr>

      {/* Expanded duplicate comparison */}
      {isExpanded && row.is_duplicate && row.existing_contact && (
        <tr className="bg-yellow-50 border-l-4 border-l-yellow-400">
          <td colSpan={columns.length + 3} className="px-5 py-4">
            <div className="space-y-2">
              <p className="text-xs font-semibold text-yellow-800 uppercase tracking-wide">
                This contact already exists in your CRM
              </p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                {row.existing_contact.company_name && (
                  <div>
                    <span className="text-gray-400 text-xs">Company</span>
                    <p className="text-gray-700">
                      {row.existing_contact.company_name}
                    </p>
                  </div>
                )}
                <div>
                  <span className="text-gray-400 text-xs">Name</span>
                  <p className="text-gray-700">
                    {[
                      row.existing_contact.first_name,
                      row.existing_contact.last_name,
                    ]
                      .filter(Boolean)
                      .join(" ") || "\u2014"}
                  </p>
                </div>
                <div>
                  <span className="text-gray-400 text-xs">Email</span>
                  <p className="text-gray-700">
                    {row.existing_contact.email || "\u2014"}
                  </p>
                </div>
                <div>
                  <span className="text-gray-400 text-xs">Title</span>
                  <p className="text-gray-700">
                    {row.existing_contact.title || "\u2014"}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3 pt-1">
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isExcluded}
                    onChange={onToggleExclude}
                    className="rounded border-gray-300 text-yellow-600 focus:ring-yellow-500"
                  />
                  <span className="text-yellow-800">
                    {isExcluded
                      ? "Excluded from import"
                      : "Uncheck to exclude this row"}
                  </span>
                </label>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function SmartImport() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Wizard state
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [analysis, setAnalysis] = useState<AnalyzeResult | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [sourceLabel, setSourceLabel] = useState("");
  const [previewData, setPreviewData] = useState<PreviewResult | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);

  // Preview table state
  const [previewPage, setPreviewPage] = useState(1);
  const [previewPageSize, setPreviewPageSize] = useState(50);
  const [previewSortBy, setPreviewSortBy] = useState<string>("");
  const [previewSortDir, setPreviewSortDir] = useState<"asc" | "desc">("asc");
  const [previewFilter, setPreviewFilter] = useState("");
  const [previewShowFilter, setPreviewShowFilter] = useState<"all" | "new" | "duplicates">("all");
  const [excludedIndices, setExcludedIndices] = useState<Set<number>>(new Set());
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());
  const [expandedDuplicate, setExpandedDuplicate] = useState<number | null>(null);

  // Accept file from ImportWizard navigation state
  const location = useLocation();
  const locationStateFile = (location.state as { file?: File } | null)?.file ?? null;

  // Mutations
  const analyzeMutation = useMutation({
    mutationFn: (f: File) => smartImportApi.analyze(f),
    onSuccess: (data) => {
      setAnalysis(data);
      // Build mapping from ALL headers, pre-select LLM matches
      const fullMapping: Record<string, string> = {};
      for (const h of data.headers ?? []) {
        fullMapping[h] = data.proposed_mapping[h] || "";
      }
      setMapping(fullMapping);
      setStep("mapping");
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
        analysis!.import_job_id,
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
        analysis!.import_job_id,
        excludedIndices.size > 0 ? [...excludedIndices] : undefined,
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
    analyzeMutation.reset();
    previewMutation.reset();
    executeMutation.reset();
  };

  // Derived
  const stepIndex = STEPS.findIndex((s) => s.key === step);

  // Filtered, sorted, paginated preview rows
  const filteredPreviewRows = useMemo(() => {
    if (!previewData) return [];
    let rows = previewData.preview_rows;

    // Status filter
    if (previewShowFilter === "new")
      rows = rows.filter((r) => !r.is_duplicate);
    else if (previewShowFilter === "duplicates")
      rows = rows.filter((r) => r.is_duplicate);

    // Text search
    if (previewFilter.trim()) {
      const q = previewFilter.toLowerCase();
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
  }, [previewData, previewFilter, previewShowFilter, previewSortBy, previewSortDir]);

  const previewTotalPages = useMemo(() => {
    if (previewPageSize === Infinity) return 1;
    return Math.max(1, Math.ceil(filteredPreviewRows.length / previewPageSize));
  }, [filteredPreviewRows.length, previewPageSize]);

  const paginatedPreviewRows = useMemo(() => {
    if (previewPageSize === Infinity) return filteredPreviewRows;
    const start = (previewPage - 1) * previewPageSize;
    return filteredPreviewRows.slice(start, start + previewPageSize);
  }, [filteredPreviewRows, previewPage, previewPageSize]);

  // Effective duplicate/new counts after exclusions
  const effectiveDuplicates = useMemo(() => {
    if (!previewData) return 0;
    return previewData.preview_rows.filter(
      (r) => r.is_duplicate && !excludedIndices.has(r._index),
    ).length;
  }, [previewData, excludedIndices]);

  const effectiveImportCount = useMemo(() => {
    if (!previewData) return 0;
    // Count non-excluded, non-duplicate rows
    return previewData.preview_rows.filter(
      (r) => !excludedIndices.has(r._index) && !r.is_duplicate,
    ).length;
  }, [previewData, excludedIndices]);

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

      {/* Step indicator */}
      <div className="flex items-center gap-4 text-sm">
        {STEPS.map((s, i) => (
          <div key={s.key} className="flex items-center gap-2">
            <span
              className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                step === s.key
                  ? "bg-gray-900 text-white"
                  : i < stepIndex
                    ? "bg-green-600 text-white"
                    : "bg-gray-200 text-gray-500"
              }`}
            >
              {i < stepIndex ? "\u2713" : i + 1}
            </span>
            <span
              className={
                step === s.key
                  ? "font-medium text-gray-900"
                  : "text-gray-500"
              }
            >
              {s.label}
            </span>
            {i < STEPS.length - 1 && (
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
          {/* Drop zone — only when no file is loaded */}
          {!file && !analyzeMutation.isPending && (
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
          {file && !analyzeMutation.isPending && (
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

          {/* Animated progress bar during LLM analysis */}
          {analyzeMutation.isPending && (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 space-y-4">
              <div className="flex items-center gap-3">
                <FileText size={20} className="text-gray-400" />
                <div>
                  <p className="text-sm font-medium text-gray-900">{file!.name}</p>
                  <p className="text-xs text-gray-500">{formatBytes(file!.size)}</p>
                </div>
              </div>
              <div className="space-y-2">
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full bg-gray-900 rounded-full animate-progress-bar" />
                </div>
                <AnalysisStatus />
              </div>
            </div>
          )}

          {/* Note about AI analysis */}
          {file && !analyzeMutation.isPending && (
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
                      <td className="px-5 py-4 text-sm text-gray-500 max-w-[200px] truncate">
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
          {/* Summary stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-white rounded-lg shadow-sm border-l-4 border-l-blue-400 p-4">
              <p className="text-sm font-medium text-gray-500">Total contacts</p>
              <p className="text-2xl font-bold text-gray-900">
                {previewData.total_contacts}
              </p>
            </div>
            <div className="bg-white rounded-lg shadow-sm border-l-4 border-l-green-400 p-4">
              <p className="text-sm font-medium text-gray-500">Companies</p>
              <p className="text-2xl font-bold text-gray-900">
                {previewData.total_companies}
              </p>
            </div>
            <div className="bg-white rounded-lg shadow-sm border-l-4 border-l-gray-200 p-4">
              <p className="text-sm font-medium text-gray-500">Will import</p>
              <p className="text-2xl font-bold text-green-700">
                {effectiveImportCount}
              </p>
            </div>
            <button
              onClick={() =>
                setPreviewShowFilter((f) => (f === "duplicates" ? "all" : "duplicates"))
              }
              className="bg-white rounded-lg shadow-sm border-l-4 border-l-yellow-400 p-4 text-left hover:bg-yellow-50 transition-colors"
            >
              <p className="text-sm font-medium text-gray-500">
                Already in CRM
              </p>
              <p className="text-2xl font-bold text-yellow-700">
                {effectiveDuplicates}
              </p>
              {previewData.duplicates > 0 && (
                <p className="text-xs text-gray-400 mt-0.5">Click to review</p>
              )}
            </button>
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
              {(["all", "new", "duplicates"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => {
                    setPreviewShowFilter(f);
                    setPreviewPage(1);
                  }}
                  className={`px-3 py-2 capitalize transition-colors ${
                    previewShowFilter === f
                      ? "bg-gray-900 text-white"
                      : "text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  {f === "all" ? "All" : f === "new" ? "To Import" : `In CRM (${previewData.duplicates})`}
                </button>
              ))}
            </div>

            {/* Bulk operations */}
            {selectedIndices.size > 0 && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-gray-500">
                  {selectedIndices.size} selected
                </span>
                <button
                  onClick={bulkExclude}
                  className="px-2.5 py-1.5 bg-red-50 text-red-700 border border-red-200 rounded-md hover:bg-red-100 transition-colors"
                >
                  Exclude
                </button>
                <button
                  onClick={bulkInclude}
                  className="px-2.5 py-1.5 bg-green-50 text-green-700 border border-green-200 rounded-md hover:bg-green-100 transition-colors"
                >
                  Include
                </button>
                <button
                  onClick={() => setSelectedIndices(new Set())}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X size={14} />
                </button>
              </div>
            )}
          </div>

          {/* Preview table */}
          <div className="bg-white rounded-lg border border-gray-200 overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-3 py-3 w-10">
                    <input
                      type="checkbox"
                      checked={
                        paginatedPreviewRows.length > 0 &&
                        selectedIndices.size === paginatedPreviewRows.length
                      }
                      onChange={toggleSelectAll}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                  </th>
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
                      onToggleExclude={() => toggleExcluded(row._index)}
                      onToggleSelect={() => toggleSelected(row._index)}
                      onToggleExpand={() =>
                        setExpandedDuplicate(isExpanded ? null : row._index)
                      }
                    />
                  );
                })}
                {paginatedPreviewRows.length === 0 && (
                  <tr>
                    <td
                      colSpan={PREVIEW_COLUMNS.length + 3}
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
                `Import ${effectiveImportCount} Contacts`
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

          <div className="grid grid-cols-3 gap-4">
            <div className="bg-green-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-green-700">
                {importResult.contacts_created}
              </p>
              <p className="text-sm text-green-600">Contacts created</p>
            </div>
            <div className="bg-blue-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-blue-700">
                {importResult.companies_created}
              </p>
              <p className="text-sm text-blue-600">Companies created</p>
            </div>
            <div className="bg-yellow-50 rounded-lg p-4 text-center">
              <p className="text-2xl font-bold text-yellow-700">
                {importResult.duplicates_skipped}
              </p>
              <p className="text-sm text-yellow-600">Duplicates skipped</p>
            </div>
          </div>

          <p className="text-sm text-gray-600">
            Imported {importResult.contacts_created} contact
            {importResult.contacts_created !== 1 ? "s" : ""} across{" "}
            {importResult.companies_created} compan
            {importResult.companies_created !== 1 ? "ies" : "y"}
          </p>

          <div className="flex gap-3 pt-2">
            <button
              onClick={() => navigate("/contacts")}
              className="px-4 py-2.5 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors"
            >
              View Contacts
            </button>
            <button
              onClick={resetAll}
              className="px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              Import More
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
