import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useLocation } from "react-router-dom";
import { Loader2, FileText, CheckCircle, X } from "lucide-react";
import { smartImportApi } from "../api/smartImport";

const DISMISSED_KEY = "import_banner_dismissed";

/**
 * Global banner that shows when an import job is running in the background.
 * Displayed in Layout — visible on every page so the user never loses track.
 * Dismissible for completed/pending jobs. Reappears on new uploads.
 */
export default function ImportStatusBanner() {
  const navigate = useNavigate();
  const location = useLocation();
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(DISMISSED_KEY));

  // Don't show on the SmartImport page itself (it has its own UI)
  const isOnImportPage = location.pathname.startsWith("/import/smart");

  const { data: activeJob } = useQuery({
    queryKey: ["import-job-active"],
    queryFn: smartImportApi.getActiveJob,
    enabled: !isOnImportPage,
    staleTime: 30_000,
    refetchInterval: (query) => {
      const job = query.state.data;
      if (!job) return false;
      if (job.status === "analyzing") return 2_000;
      return false;
    },
  });

  if (!activeJob || isOnImportPage) return null;

  // Hide if user dismissed this specific job
  if (dismissed === String(activeJob.id)) return null;

  // Hide completed jobs automatically
  if (activeJob.status === "completed" || activeJob.status === "imported") return null;

  const isAnalyzing = activeJob.status === "analyzing";
  const isPending = activeJob.status === "pending";
  const filename = activeJob.filename ?? "CSV file";

  return (
    <div className="w-full flex items-center gap-3 px-4 py-2.5 bg-blue-50 border-b border-blue-100">
      <button
        onClick={() => navigate(`/import/smart?job=${activeJob.id}`)}
        className="flex items-center gap-3 flex-1 text-left hover:bg-blue-100 rounded transition-colors -mx-1 px-1"
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
      {isPending && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            localStorage.setItem(DISMISSED_KEY, String(activeJob.id));
            setDismissed(String(activeJob.id));
          }}
          className="text-blue-400 hover:text-blue-600 shrink-0 p-1"
          aria-label="Dismiss"
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
}
