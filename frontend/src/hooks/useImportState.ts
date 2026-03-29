import { useState, useCallback } from "react";
import { useDebouncedValue } from "./useDebouncedValue";
import type {
  AnalyzeResult,
  PreviewResult,
  ImportResult,
  RowDecision,
} from "../api/smartImport";

type Step = "upload" | "mapping" | "preview";
type ShowFilter = "all" | "new" | "matches" | "file_dupes";

export function useImportState(initialJobId: string | null) {
  // Job ID persisted in URL — survives navigation
  const [jobId, setJobId] = useState<string | null>(initialJobId);

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
  const debouncedPreviewFilter = useDebouncedValue(previewFilter, 300);
  const [previewShowFilter, setPreviewShowFilter] = useState<ShowFilter>("all");
  const [excludedIndices, setExcludedIndices] = useState<Set<number>>(new Set());
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set());
  const [expandedDuplicate, setExpandedDuplicate] = useState<number | null>(null);
  const [rowDecisions, setRowDecisions] = useState<Record<number, RowDecision>>({});
  const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(null);

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

  return {
    // Job
    jobId, setJobId,
    // Wizard
    step, setStep,
    file, setFile,
    dragOver, setDragOver,
    analysis, setAnalysis,
    mapping, setMapping,
    sourceLabel, setSourceLabel,
    previewData, setPreviewData,
    importResult, setImportResult,
    // Preview table
    previewPage, setPreviewPage,
    previewPageSize, setPreviewPageSize,
    previewSortBy, setPreviewSortBy,
    previewSortDir, setPreviewSortDir,
    previewFilter, setPreviewFilter,
    debouncedPreviewFilter,
    previewShowFilter, setPreviewShowFilter,
    excludedIndices, setExcludedIndices,
    selectedIndices, setSelectedIndices,
    expandedDuplicate, setExpandedDuplicate,
    rowDecisions, setRowDecisions,
    selectedCampaignId, setSelectedCampaignId,
    // Callbacks
    applyAnalysisResult,
  };
}

export type ImportState = ReturnType<typeof useImportState>;
