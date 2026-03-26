import React from "react";
import type {
  PreviewRow,
  RowAction,
  RowDecision,
} from "../api/smartImport";
import {
  MatchStatusBadge,
  ComparisonPanel,
} from "../components/DuplicateComparisonPanel";

/** Single row in the preview table with comparison panel for matches. */
function PreviewTableRowInner({
  row,
  columns,
  isExcluded,
  isSelected,
  isExpanded,
  decision,
  onToggleExclude,
  onToggleSelect,
  onToggleExpand,
  onDecision,
}: {
  row: PreviewRow;
  columns: readonly { readonly key: string; readonly label: string }[];
  isExcluded: boolean;
  isSelected: boolean;
  isExpanded: boolean;
  decision?: RowDecision;
  onToggleExclude: () => void;
  onToggleSelect: () => void;
  onToggleExpand: () => void;
  onDecision: (action: RowAction) => void;
}) {
  const rowOpacity = isExcluded ? "opacity-40" : "";

  return (
    <>
      <tr
        className={`hover:bg-gray-50 transition-colors ${rowOpacity} ${
          row.is_duplicate ? "bg-yellow-50/50" : ""
        }`}
      >
        <td className="px-3 py-3 text-center">
          <input
            type="checkbox"
            checked={!isExcluded}
            onChange={onToggleExclude}
            className="rounded border-gray-300 text-green-600 focus:ring-green-500"
          />
        </td>
        <td className="px-3 py-3">
          <MatchStatusBadge
            row={row}
            decision={decision}
            isExpanded={isExpanded}
            onToggleExpand={onToggleExpand}
          />
        </td>
        {columns.map((col) => {
          const val = row[col.key];
          const existing = row.existing_contact;
          const crmVal = existing ? (existing as unknown as Record<string, unknown>)[col.key === "full_name" ? "first_name" : col.key] : null;
          const diffs = row.field_diffs as unknown as Record<string, string> | null;
          const hasConflict = diffs && col.key in diffs && diffs[col.key] === "conflict";
          return (
            <td
              key={col.key}
              className={`px-4 py-3 text-sm whitespace-nowrap max-w-[280px] truncate cursor-default ${hasConflict ? "text-amber-700 font-medium" : "text-gray-600"}`}
              title={val != null ? `Import: ${String(val)}${crmVal && hasConflict ? `\nCRM: ${String(crmVal)}` : ""}` : undefined}
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

      {/* CRM context row — ONLY when there are field differences */}
      {row.existing_contact && row.match_type && !isExpanded && (() => {
        const d = row.field_diffs as unknown as Record<string, string> | null;
        const hasDiffs = d && Object.values(d).some((v) => v === "conflict" || v === "new");
        if (!hasDiffs) return null;
        return (
          <tr className="bg-gray-50/80 border-t-0">
            <td />
            <td />
            <td className="px-3 py-1.5">
              <span className="text-xs text-gray-400">CRM</span>
            </td>
            {columns.map((col) => {
              const existing = row.existing_contact!;
              const key = col.key === "full_name"
                ? `${existing.first_name || ""} ${existing.last_name || ""}`.trim()
                : (existing as unknown as Record<string, unknown>)[col.key];
              const val = key != null ? String(key) : null;
              const colDiff = d && col.key in d ? d[col.key] : null;
              const show = colDiff === "conflict" || colDiff === "new";
              return (
                <td
                  key={col.key}
                  className={`px-4 py-1.5 text-xs whitespace-nowrap max-w-[280px] truncate ${show ? "text-amber-600 font-medium" : "text-gray-300"}`}
                  title={val || undefined}
                >
                  {show ? (val || <span className="text-gray-300">&mdash;</span>) : ""}
                </td>
              );
            })}
          </tr>
        );
      })()}

      {/* LinkedIn link row — only for rows with differences */}
      {row.existing_contact && row.match_type && !isExpanded && row.linkedin_url && (() => {
        const d = row.field_diffs as unknown as Record<string, string> | null;
        const hasDiffs = d && Object.values(d).some((v) => v === "conflict" || v === "new");
        if (!hasDiffs) return null;
        return (
          <tr className="bg-gray-50/80">
            <td colSpan={2} />
            <td colSpan={columns.length} className="px-4 py-1 pb-2">
              <a
                href={row.linkedin_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 font-medium"
            >
              Verify on LinkedIn &rarr;
            </a>
          </td>
        </tr>
        );
      })()}

      {/* Expandable comparison panel for any match */}
      {isExpanded && row.existing_contact && (
        <ComparisonPanel row={row} onDecision={onDecision} />
      )}
    </>
  );
}

const PreviewTableRow = React.memo(PreviewTableRowInner, (prev, next) => {
  return (
    prev.row._index === next.row._index &&
    prev.isExcluded === next.isExcluded &&
    prev.isSelected === next.isSelected &&
    prev.isExpanded === next.isExpanded &&
    prev.decision?.action === next.decision?.action
  );
});

export default PreviewTableRow;
