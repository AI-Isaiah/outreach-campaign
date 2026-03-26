import { CheckCircle, Download, Zap } from "lucide-react";
import { api } from "../../api/client";
import type { ResearchJobDetail as ResearchJobDetailType } from "../../types";

export default function CompletionSummary({
  jobData,
  onBatchImport,
}: {
  jobData: ResearchJobDetailType;
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
