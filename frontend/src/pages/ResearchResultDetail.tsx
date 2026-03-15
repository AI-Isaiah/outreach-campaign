import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, UserPlus } from "lucide-react";
import { api } from "../api/client";
import CryptoScoreBadge from "../components/CryptoScoreBadge";

export default function ResearchResultDetail() {
  const { id } = useParams<{ id: string }>();
  const resultId = Number(id);
  const queryClient = useQueryClient();

  const { data: result, isLoading } = useQuery({
    queryKey: ["research-result", resultId],
    queryFn: () => api.getResearchResult(resultId),
  });

  const importMutation = useMutation({
    mutationFn: (indices: number[]) => api.importDiscoveredContacts(resultId, indices),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["research-result", resultId] }),
  });

  if (isLoading) {
    return <div className="h-64 bg-gray-100 rounded-lg animate-pulse" />;
  }

  if (!result) {
    return <p className="text-gray-500">Result not found</p>;
  }

  const scoreColor = (result.crypto_score ?? 0) >= 80 ? "text-green-600" :
    (result.crypto_score ?? 0) >= 60 ? "text-blue-600" :
    (result.crypto_score ?? 0) >= 40 ? "text-yellow-600" :
    (result.crypto_score ?? 0) >= 20 ? "text-gray-500" : "text-red-600";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to={`/research/${result.job_id}`} className="text-gray-400 hover:text-gray-600">
          <ArrowLeft size={20} />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">{result.company_name}</h1>
            <CryptoScoreBadge score={result.crypto_score} showLabel />
          </div>
          <div className="flex items-center gap-3 mt-1">
            {result.company_website && (
              <a
                href={result.company_website.startsWith("http") ? result.company_website : `https://${result.company_website}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-600 hover:underline inline-flex items-center gap-1"
              >
                {result.company_website} <ExternalLink size={12} />
              </a>
            )}
            {result.company_id && (
              <Link to={`/companies/${result.company_id}`} className="text-sm text-blue-600 hover:underline">
                View in CRM
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* Score Gauge */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-center gap-8">
          <div className="text-center">
            <p className={`text-5xl font-bold tabular-nums ${scoreColor}`}>
              {result.crypto_score ?? "?"}
            </p>
            <p className="text-sm text-gray-500 mt-1">Crypto Score</p>
          </div>
          <div className="flex-1">
            {/* Score bar */}
            <div className="h-3 w-full rounded-full bg-gray-100 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  (result.crypto_score ?? 0) >= 80 ? "bg-green-500" :
                  (result.crypto_score ?? 0) >= 60 ? "bg-blue-500" :
                  (result.crypto_score ?? 0) >= 40 ? "bg-yellow-500" :
                  (result.crypto_score ?? 0) >= 20 ? "bg-gray-400" : "bg-red-500"
                }`}
                style={{ width: `${result.crypto_score ?? 0}%` }}
              />
            </div>
            <div className="flex justify-between text-[10px] text-gray-400 mt-1">
              <span>Unlikely</span>
              <span>No Signal</span>
              <span>Possible</span>
              <span>Likely</span>
              <span>Confirmed</span>
            </div>
          </div>
        </div>
      </div>

      {/* Evidence Summary */}
      {result.evidence_summary && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-medium text-gray-700 mb-2">Evidence Summary</h2>
          <p className="text-gray-700">{result.evidence_summary}</p>
        </div>
      )}

      {/* Evidence List */}
      {result.evidence_json && result.evidence_json.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-medium text-gray-700 mb-3">Evidence</h2>
          <div className="space-y-3">
            {result.evidence_json.map((ev, i) => (
              <div key={i} className="flex gap-3 rounded-md bg-gray-50 p-3">
                <span className={`self-start mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                  ev.relevance === "high" ? "bg-green-100 text-green-700" :
                  ev.relevance === "medium" ? "bg-yellow-100 text-yellow-700" :
                  "bg-gray-100 text-gray-600"
                }`}>
                  {ev.relevance}
                </span>
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-1">{ev.source}</p>
                  <p className="text-sm text-gray-700 italic">"{ev.quote}"</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Discovered Contacts */}
      {result.discovered_contacts_json && result.discovered_contacts_json.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-gray-700">Discovered Contacts</h2>
            <button
              onClick={() => importMutation.mutate(
                result.discovered_contacts_json!.map((_, i) => i)
              )}
              disabled={importMutation.isPending}
              className="flex items-center gap-1.5 rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <UserPlus size={14} />
              {importMutation.isPending ? "Importing..." :
                importMutation.isSuccess ? `Imported ${importMutation.data.imported}` :
                "Import All to CRM"}
            </button>
          </div>
          <div className="bg-gray-50 rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="border-b border-gray-200">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Name</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Title</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Email</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">LinkedIn</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {result.discovered_contacts_json.map((c, i) => (
                  <tr key={i}>
                    <td className="px-4 py-2.5 text-sm font-medium text-gray-900">{c.name}</td>
                    <td className="px-4 py-2.5 text-sm text-gray-600">{c.title}</td>
                    <td className="px-4 py-2.5 text-sm text-gray-500">{c.email || "--"}</td>
                    <td className="px-4 py-2.5">
                      {c.linkedin ? (
                        <a href={c.linkedin} target="_blank" rel="noopener noreferrer" className="text-sm text-blue-600 hover:underline">
                          Profile
                        </a>
                      ) : (
                        <span className="text-sm text-gray-400">--</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-400">{c.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Warm Intros */}
      {result.warm_intro_notes && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-medium text-gray-700 mb-2">Warm Introduction Paths</h2>
          <div className="rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-800 whitespace-pre-line">
            {result.warm_intro_notes}
          </div>
          {result.warm_intro_contact_ids && result.warm_intro_contact_ids.length > 0 && (
            <div className="flex gap-2 mt-2">
              {result.warm_intro_contact_ids.map((cid) => (
                <Link
                  key={cid}
                  to={`/contacts/${cid}`}
                  className="text-xs text-blue-600 hover:underline"
                >
                  Contact #{cid}
                </Link>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Classification Reasoning */}
      {result.classification_reasoning && (
        <details className="bg-white rounded-lg border border-gray-200 p-5">
          <summary className="cursor-pointer text-sm font-medium text-gray-700">
            Classification Reasoning
          </summary>
          <p className="mt-2 text-sm text-gray-600">{result.classification_reasoning}</p>
        </details>
      )}
    </div>
  );
}
