import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Users, TrendingUp } from "lucide-react";
import { api } from "../../api/client";
import type { ResearchResult } from "../../types";
import CryptoScoreBadge from "../CryptoScoreBadge";

const CATEGORY_CONFIG: Record<string, { bg: string; text: string; label: string; color: string }> = {
  confirmed_investor: { bg: "bg-green-100", text: "text-green-700", label: "Confirmed", color: "#16A34A" },
  likely_interested: { bg: "bg-blue-100", text: "text-blue-700", label: "Likely", color: "#2563EB" },
  possible: { bg: "bg-yellow-100", text: "text-yellow-700", label: "Possible", color: "#D97706" },
  no_signal: { bg: "bg-gray-100", text: "text-gray-600", label: "No Signal", color: "#6B7280" },
  unlikely: { bg: "bg-red-100", text: "text-red-700", label: "Unlikely", color: "#DC2626" },
};

export { CATEGORY_CONFIG };

export function ResultRow({ result, selected, onSelect, onExpand }: {
  result: ResearchResult;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  onExpand: () => void;
}) {
  const hasWarmIntros = result.warm_intro_contact_ids && result.warm_intro_contact_ids.length > 0;
  const contactCount = result.discovered_contacts_json?.length || 0;

  return (
    <tr className="hover:bg-gray-50 transition-colors">
      <td className="px-3 py-4">
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => onSelect(e.target.checked)}
          className="rounded border-gray-300 text-blue-600"
          onClick={(e) => e.stopPropagation()}
        />
      </td>
      <td className="px-4 py-4 cursor-pointer" onClick={onExpand}>
        <p className="text-sm font-medium text-gray-900">{result.company_name}</p>
        {result.company_website && (
          <p className="text-xs text-gray-400 truncate max-w-[200px]">{result.company_website}</p>
        )}
      </td>
      <td className="px-4 py-4">
        <CryptoScoreBadge score={result.crypto_score} />
      </td>
      <td className="px-4 py-4">
        {result.category && (
          <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
            CATEGORY_CONFIG[result.category]?.bg || ""} ${CATEGORY_CONFIG[result.category]?.text || ""
          }`}>
            {CATEGORY_CONFIG[result.category]?.label || result.category}
          </span>
        )}
      </td>
      <td className="px-4 py-4">
        <p className="text-sm text-gray-600 line-clamp-2 max-w-xs">{result.evidence_summary || "\u2014"}</p>
      </td>
      <td className="px-4 py-4">
        {contactCount > 0 && (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-gray-600">
            <Users size={13} /> {contactCount}
          </span>
        )}
      </td>
      <td className="px-4 py-4">
        {hasWarmIntros && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
            <TrendingUp size={10} /> Warm
          </span>
        )}
      </td>
    </tr>
  );
}

export function ExpandedResult({ result }: { result: ResearchResult }) {
  const queryClient = useQueryClient();
  const importMutation = useMutation({
    mutationFn: (indices: number[]) => api.importDiscoveredContacts(result.id, indices),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["research-results"] }),
  });

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-base font-semibold text-gray-900">{result.company_name}</h3>
          {result.company_id && (
            <Link to={`/companies/${result.company_id}`} className="text-xs text-blue-600 hover:underline">
              View in CRM
            </Link>
          )}
        </div>
        <CryptoScoreBadge score={result.crypto_score} showLabel />
      </div>

      {result.evidence_summary && (
        <p className="text-sm text-gray-600 bg-gray-50 rounded-lg px-4 py-3">{result.evidence_summary}</p>
      )}

      {result.evidence_json && result.evidence_json.length > 0 && (
        <div className="space-y-2">
          {result.evidence_json.map((ev, i) => (
            <div key={i} className="flex gap-2 text-sm">
              <span className={`shrink-0 mt-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                ev.relevance === "high" ? "bg-green-100 text-green-700" :
                ev.relevance === "medium" ? "bg-yellow-100 text-yellow-700" : "bg-gray-100 text-gray-600"
              }`}>{ev.relevance}</span>
              <div>
                <span className="text-xs text-gray-400">{ev.source}</span>
                <p className="text-gray-700 italic">"{ev.quote}"</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {result.discovered_contacts_json && result.discovered_contacts_json.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Discovered Contacts</h4>
            <button
              onClick={() => importMutation.mutate(result.discovered_contacts_json!.map((_, i) => i))}
              disabled={importMutation.isPending}
              className="rounded bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {importMutation.isPending ? "..." : importMutation.isSuccess ? `Imported ${importMutation.data.imported}` : "Import All"}
            </button>
          </div>
          <div className="bg-gray-50 rounded-lg divide-y divide-gray-100 text-sm">
            {result.discovered_contacts_json.map((c, i) => (
              <div key={i} className="px-3 py-2 flex items-center justify-between">
                <div>
                  <span className="font-medium text-gray-900">{c.name}</span>
                  <span className="text-gray-400 ml-2">{c.title}</span>
                </div>
                <div className="flex gap-3 text-xs text-gray-500">
                  {c.email && <span>{c.email}</span>}
                  {c.linkedin && <a href={c.linkedin} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">LinkedIn</a>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {result.warm_intro_notes && (
        <div className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 whitespace-pre-line">
          <p className="text-xs font-semibold uppercase tracking-wide text-amber-600 mb-1">Warm Intros</p>
          {result.warm_intro_notes}
        </div>
      )}
    </div>
  );
}
