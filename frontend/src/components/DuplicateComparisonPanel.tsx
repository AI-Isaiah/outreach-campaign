import { ChevronDown, ChevronRight, Building2, ExternalLink } from "lucide-react";
import type {
  PreviewRow,
  RowAction,
  RowDecision,
  DiffStatus,
} from "../api/smartImport";

const COMPARE_FIELDS = [
  "first_name",
  "last_name",
  "email",
  "title",
  "linkedin_url",
] as const;

const FIELD_LABELS: Record<string, string> = {
  first_name: "First name",
  last_name: "Last name",
  email: "Email",
  title: "Title",
  linkedin_url: "LinkedIn",
};

function DiffBadge({ status }: { status: DiffStatus }) {
  const styles: Record<DiffStatus, string> = {
    new: "bg-green-200 text-green-800",
    conflict: "bg-amber-200 text-amber-800",
    same: "bg-gray-200 text-gray-600",
    empty: "bg-gray-100 text-gray-400",
  };
  const labels: Record<DiffStatus, string> = {
    new: "NEW",
    conflict: "DIFF",
    same: "SAME",
    empty: "\u2014",
  };
  return (
    <span
      className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium ${styles[status]}`}
    >
      {labels[status]}
    </span>
  );
}

function DecisionBadge({ decision }: { decision: RowDecision }) {
  const styles: Record<RowAction, string> = {
    merge: "bg-blue-100 text-blue-700",
    enroll: "bg-green-100 text-green-700",
    skip: "bg-gray-100 text-gray-500",
    import: "bg-green-100 text-green-700",
  };
  const labels: Record<RowAction, string> = {
    merge: "Will merge",
    enroll: "Will enroll",
    skip: "Will skip",
    import: "Will import",
  };
  return (
    <span
      className={`ml-1.5 inline-block rounded-full px-2 py-0.5 text-[10px] font-medium ${styles[decision.action]}`}
    >
      {labels[decision.action]}
    </span>
  );
}

/** Status badge shown in the preview table row. */
export function MatchStatusBadge({
  row,
  decision,
  isExpanded,
  onToggleExpand,
}: {
  row: PreviewRow;
  decision?: RowDecision;
  isExpanded: boolean;
  onToggleExpand: () => void;
}) {
  return (
    <>
      {row.within_file_duplicate ? (
        <span
          className="inline-block rounded-full px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-700 cursor-default"
          title={`Same contact appears multiple times in this CSV (row ${(row.within_file_duplicate_of ?? 0) + 1} is the first occurrence)`}
        >
          File duplicate
        </span>
      ) : row.match_type === "exact" ? (
        <button
          onClick={onToggleExpand}
          className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800 hover:bg-yellow-200 transition-colors"
          title="This contact already exists in your CRM — email and LinkedIn both match. Click to compare."
        >
          {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          Already in CRM
        </button>
      ) : row.match_type ? (
        <button
          onClick={onToggleExpand}
          className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 hover:bg-blue-200 transition-colors"
          title={
            row.match_type === "email_only"
              ? "A contact with this email already exists in your CRM. Click to compare."
              : row.match_type === "linkedin_only"
                ? "A contact with this LinkedIn URL already exists in your CRM. Click to compare."
                : "This email and LinkedIn match different contacts in your CRM. Click to compare."
          }
        >
          {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {row.match_type === "email_only"
            ? "Email match"
            : row.match_type === "linkedin_only"
              ? "LinkedIn match"
              : "Partial match"}
        </button>
      ) : (
        <span
          className="inline-block rounded-full px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 cursor-default"
          title="No matching contact found in your CRM — will be imported as new"
        >
          New
        </span>
      )}
      {decision && <DecisionBadge decision={decision} />}
    </>
  );
}

/** Expandable side-by-side comparison panel for matched contacts. */
export function ComparisonPanel({
  row,
  onDecision,
}: {
  row: PreviewRow;
  onDecision: (action: RowAction) => void;
}) {
  if (!row.existing_contact || !row.field_diffs) return null;

  return (
    <tr className="bg-gray-50">
      <td colSpan={100} className="px-5 py-4">
        <div className="space-y-3">
          {/* Company change banner */}
          {row.resolution_tier === "company_change" && row.existing_company_name && (
            <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-lg p-3">
              <Building2 size={16} className="text-amber-600 shrink-0" />
              <span className="text-sm text-amber-800 font-medium">
                Likely moved: {row.existing_company_name} &rarr; {row.company_name}
              </span>
            </div>
          )}
          {/* LinkedIn verification link */}
          {row.linkedin_url && (
            <a
              href={row.linkedin_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600 hover:text-blue-700"
              aria-label={`Open LinkedIn profile for ${row.full_name || "contact"}`}
            >
              <ExternalLink size={14} />
              Verify on LinkedIn
            </a>
          )}
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Side-by-side comparison
          </p>
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-100">
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 w-28">
                    Field
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">
                    Import Value
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">
                    CRM Value
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 w-20">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {COMPARE_FIELDS.map((field) => {
                  const diff = row.field_diffs![field];
                  const importVal = row[field] ?? "";
                  const crmVal = row.existing_contact![field] ?? "";
                  return (
                    <tr
                      key={field}
                      className={
                        diff === "new"
                          ? "bg-green-50"
                          : diff === "conflict"
                            ? "bg-amber-50"
                            : ""
                      }
                    >
                      <td className="px-3 py-2 text-xs font-medium text-gray-500">
                        {FIELD_LABELS[field]}
                      </td>
                      <td className="px-3 py-2 text-gray-900">
                        {String(importVal) || (
                          <span className="text-gray-300">&mdash;</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-gray-900">
                        {String(crmVal) || (
                          <span className="text-gray-300">&mdash;</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <DiffBadge status={diff} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={() => onDecision("merge")}
              className="px-3 py-1.5 bg-blue-600 text-white rounded text-xs font-medium hover:bg-blue-700 transition-colors"
            >
              Merge & Enroll
            </button>
            <button
              onClick={() => onDecision("enroll")}
              className="px-3 py-1.5 bg-green-600 text-white rounded text-xs font-medium hover:bg-green-700 transition-colors"
            >
              Enroll Only
            </button>
            <button
              onClick={() => onDecision("skip")}
              className="px-3 py-1.5 bg-white border border-gray-200 text-gray-600 rounded text-xs font-medium hover:bg-gray-50 transition-colors"
            >
              Skip
            </button>
            <button
              onClick={() => onDecision("import")}
              className="px-3 py-1.5 bg-white border border-gray-200 text-gray-600 rounded text-xs font-medium hover:bg-gray-50 transition-colors"
            >
              Import as New
            </button>
          </div>
        </div>
      </td>
    </tr>
  );
}
