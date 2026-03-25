import { useQuery } from "@tanstack/react-query";
import { useNavigate, useLocation } from "react-router-dom";
import { Loader2, FileText, CheckCircle } from "lucide-react";
import { smartImportApi } from "../api/smartImport";

/**
 * Global banner that shows when an import job is running in the background.
 * Displayed in Layout — visible on every page so the user never loses track.
 */
export default function ImportStatusBanner() {
  const navigate = useNavigate();
  const location = useLocation();

  // Don't show on the SmartImport page itself (it has its own UI)
  const isOnImportPage = location.pathname.startsWith("/import/smart");

  const { data: activeJob } = useQuery({
    queryKey: ["import-job-active"],
    queryFn: smartImportApi.getActiveJob,
    enabled: !isOnImportPage,
    staleTime: 30_000,
    refetchInterval: (query) => {
      const job = query.state.data;
      if (!job) return false; // no active job — stop polling, rely on staleTime
      if (job.status === "analyzing") return 2_000;
      return false;
    },
  });

  if (!activeJob || isOnImportPage) return null;

  const isAnalyzing = activeJob.status === "analyzing";
  const isPending = activeJob.status === "pending";
  const filename = activeJob.filename ?? "CSV file";

  return (
    <button
      onClick={() => navigate(`/import/smart?job=${activeJob.id}`)}
      className="w-full flex items-center gap-3 px-4 py-2.5 bg-blue-50 border-b border-blue-100 text-left hover:bg-blue-100 transition-colors"
    >
      {isAnalyzing ? (
        <Loader2 size={16} className="text-blue-600 animate-spin shrink-0" />
      ) : isPending ? (
        <CheckCircle size={16} className="text-green-600 shrink-0" />
      ) : (
        <FileText size={16} className="text-blue-600 shrink-0" />
      )}
      <span className="text-sm text-blue-800 font-medium truncate">
        {isAnalyzing
          ? `Analyzing ${filename}...`
          : isPending
            ? `${filename} ready for mapping`
            : `Import in progress: ${filename}`}
      </span>
      <span className="text-xs text-blue-600 ml-auto shrink-0">
        {isAnalyzing ? "Running" : "Resume"} &rarr;
      </span>
    </button>
  );
}
