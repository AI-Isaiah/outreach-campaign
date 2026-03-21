import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { request } from "../api/request";

interface CryptoSignal {
  source: string;
  quote: string;
  relevance: "high" | "medium" | "low";
}

interface KeyPerson {
  name: string;
  title: string;
  linkedin_url: string | null;
  context: string;
}

interface TalkingPoint {
  hook_type: string;
  text: string;
  source_reference: string;
}

interface DeepResearchResult {
  id: number;
  company_id: number;
  status: "pending" | "researching" | "synthesizing" | "completed" | "failed" | "cancelled";
  company_overview: string | null;
  crypto_signals: CryptoSignal[] | null;
  key_people: KeyPerson[] | null;
  talking_points: TalkingPoint[] | null;
  risk_factors: string | null;
  updated_crypto_score: number | null;
  previous_crypto_score: number | null;
  confidence: string | null;
  cost_estimate_usd: number | null;
  actual_cost_usd: number | null;
  query_count: number | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

const ACTIVE_STATUSES = new Set(["pending", "researching", "synthesizing"]);

const STEP_LABELS = [
  "Investment thesis",
  "Recent moves",
  "Team & hires",
  "Portfolio",
  "News & events",
  "Synthesize",
];

const RELEVANCE_CLASSES: Record<string, string> = {
  high: "bg-green-100 text-green-800",
  medium: "bg-yellow-100 text-yellow-800",
  low: "bg-gray-100 text-gray-800",
};

function stepProgress(status: string, queryCount: number | null): number {
  if (status === "pending") return 0;
  if (status === "synthesizing") return (queryCount ?? 5);
  if (status === "researching") return Math.max(1, Math.floor((queryCount ?? 5) / 2));
  return queryCount ?? 5;
}

export default function DeepResearchBrief({ companyId, companyName }: { companyId: number; companyName: string }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [showConfirm, setShowConfirm] = useState(false);

  const { data: result, isLoading } = useQuery<DeepResearchResult>({
    queryKey: ["deep-research", companyId],
    queryFn: () => request<DeepResearchResult>(`/research/deep/${companyId}`),
    retry: false,
    refetchInterval: (query) => {
      const d = query.state.data;
      if (d && ACTIVE_STATUSES.has(d.status)) return 3000;
      return false;
    },
  });

  const triggerMutation = useMutation({
    mutationFn: () => request<DeepResearchResult>(`/research/deep/${companyId}`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["deep-research", companyId] }),
  });

  const cancelMutation = useMutation({
    mutationFn: (drId: number) => request(`/research/deep/${drId}/cancel`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["deep-research", companyId] }),
  });

  const handleTrigger = useCallback(() => {
    setShowConfirm(false);
    triggerMutation.mutate();
  }, [triggerMutation]);

  if (isLoading) return null;

  const isActive = result && ACTIVE_STATUSES.has(result.status);
  const isCompleted = result?.status === "completed";
  const isFailed = result?.status === "failed";

  // State 1: No result or terminal non-completed — show trigger button
  if (!result || result.status === "cancelled" || (isFailed && !result.company_overview)) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-semibold text-gray-900">Deep Research</h2>
            <p className="text-sm text-gray-500 mt-1">
              Generate a structured brief with talking points for outreach
            </p>
          </div>
          <div className="relative text-right">
            <button
              onClick={() => setShowConfirm(true)}
              disabled={triggerMutation.isPending}
              className="bg-gray-900 text-white rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-gray-800 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              {triggerMutation.isPending ? "Starting..." : "Run Deep Research"}
            </button>
            <div className="text-xs text-gray-400 mt-1">~$0.08 / ~2 min / 6 queries</div>
            {showConfirm && (
              <div className="absolute right-0 top-12 bg-white border border-gray-200 rounded-lg shadow-lg p-4 z-10 w-72">
                <p className="text-sm text-gray-700 mb-3">
                  Run deep research on <span className="font-medium">{companyName}</span>? ~$0.08 / ~2 min
                </p>
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setShowConfirm(false)} className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5">
                    Cancel
                  </button>
                  <button onClick={handleTrigger} className="bg-gray-900 text-white rounded px-3 py-1.5 text-sm font-medium hover:bg-gray-800">
                    Run
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
        {triggerMutation.isError && (
          <p className="text-sm text-red-600 mt-3">{(triggerMutation.error as Error).message}</p>
        )}
        {isFailed && result.error_message && (
          <div className="mt-3 border-l-4 border-red-400 bg-red-50 p-3 rounded-r">
            <p className="text-sm text-red-700">{result.error_message}</p>
          </div>
        )}
      </div>
    );
  }

  // State 2: In progress
  if (isActive) {
    const completed = stepProgress(result.status, result.query_count);
    const total = STEP_LABELS.length;
    const pct = Math.round((completed / total) * 100);

    return (
      <div className="bg-white rounded-lg border border-gray-200 p-5" role="region" aria-label={`Deep research in progress for ${companyName}`}>
        <div className="flex justify-between items-center">
          <h2 className="font-semibold text-gray-900">Deep Research: {companyName}</h2>
          <span className="text-xs text-gray-400">
            ${result.actual_cost_usd?.toFixed(3) ?? "0.000"} spent
          </span>
        </div>
        <div className="h-1.5 bg-gray-200 rounded-full mt-3" role="progressbar" aria-valuenow={completed} aria-valuemax={total}>
          <div className="h-1.5 bg-blue-600 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3">
          {STEP_LABELS.map((label, i) => {
            const done = i < completed;
            const active = i === completed && result.status !== "pending";
            return (
              <div key={label} className={`flex items-center gap-1.5 text-xs ${done ? "text-green-600" : active ? "text-blue-600 font-semibold" : "text-gray-400"}`}>
                <div className={`w-2 h-2 rounded-full ${done ? "bg-green-600" : active ? "bg-blue-600" : "bg-gray-200"}`} />
                {label}
              </div>
            );
          })}
        </div>
        <div className="mt-4">
          <button
            onClick={() => cancelMutation.mutate(result.id)}
            disabled={cancelMutation.isPending}
            className="text-sm text-gray-500 hover:text-gray-700 border border-gray-200 rounded px-3 py-1.5 focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  // State 2b: Failed with error
  if (isFailed) {
    return (
      <div className="bg-white rounded-lg border-l-4 border-red-400 border-y border-r border-gray-200 p-5" role="alert">
        <div className="flex items-start gap-3">
          <svg className="w-5 h-5 text-red-500 mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" strokeWidth="2" />
            <path strokeWidth="2" d="M12 8v4m0 4h.01" />
          </svg>
          <div className="flex-1">
            <h3 className="font-semibold text-gray-900">Deep Research Failed</h3>
            <p className="text-sm text-gray-700 mt-1">{result.error_message || "An unexpected error occurred"}</p>
            <p className="text-xs text-gray-400 mt-2">${result.actual_cost_usd?.toFixed(3) ?? "0"} spent</p>
            <div className="flex gap-3 mt-3">
              <button
                onClick={() => setShowConfirm(true)}
                className="bg-gray-900 text-white rounded px-3 py-1.5 text-sm font-medium hover:bg-gray-800 focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
              >
                Retry
              </button>
              <button
                onClick={() => queryClient.setQueryData(["deep-research", companyId], null)}
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
        {showConfirm && (
          <div className="mt-3 bg-gray-50 border border-gray-200 rounded-lg p-3">
            <p className="text-sm text-gray-700">Retry deep research on <span className="font-medium">{companyName}</span>? ~$0.08</p>
            <div className="flex gap-2 mt-2">
              <button onClick={handleTrigger} className="bg-gray-900 text-white rounded px-3 py-1.5 text-sm font-medium hover:bg-gray-800">Run</button>
              <button onClick={() => setShowConfirm(false)} className="text-sm text-gray-500 px-3 py-1.5">Cancel</button>
            </div>
          </div>
        )}
      </div>
    );
  }

  // State 3: Completed brief
  if (!isCompleted) return null;

  const isPartial = !result.crypto_signals && !result.key_people && !result.talking_points;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden" role="region" aria-label={`Deep research brief for ${companyName}`}>
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-100 flex justify-between items-center">
        <div>
          <h2 className="font-semibold text-gray-900">Deep Research Brief</h2>
          <span className="text-xs text-gray-400">
            {result.completed_at ? new Date(result.completed_at).toLocaleDateString() : ""} · ${result.actual_cost_usd?.toFixed(3) ?? ""}
          </span>
        </div>
        {result.updated_crypto_score != null && (
          <span
            className={`rounded-full px-3 py-1 text-sm font-semibold ${result.updated_crypto_score >= 60 ? "bg-green-100 text-green-800" : result.updated_crypto_score >= 40 ? "bg-yellow-100 text-yellow-800" : "bg-gray-100 text-gray-700"}`}
            aria-label={result.previous_crypto_score != null ? `Crypto score updated from ${result.previous_crypto_score} to ${result.updated_crypto_score}` : `Deep research score: ${result.updated_crypto_score}`}
          >
            {result.previous_crypto_score != null
              ? `${result.previous_crypto_score} → ${result.updated_crypto_score}`
              : `Score: ${result.updated_crypto_score}`}
          </span>
        )}
      </div>

      {isPartial && (
        <div className="mx-5 mt-4 bg-amber-50 border border-amber-200 rounded-md p-3 text-sm text-amber-800">
          Partial results — synthesis could not produce structured output. Raw overview shown below.
        </div>
      )}

      {/* Company Overview */}
      {result.company_overview && (
        <div className="px-5 py-4 border-b border-gray-100">
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Company Overview</div>
          <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">{result.company_overview}</p>
        </div>
      )}

      {/* Crypto Signals */}
      {result.crypto_signals && result.crypto_signals.length > 0 && (
        <div className="px-5 py-4 border-b border-gray-100">
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Crypto & Digital Asset Signals</div>
          <div className="space-y-2">
            {result.crypto_signals.map((s, i) => (
              <div key={i} className="bg-gray-50 border border-gray-100 rounded-md p-3">
                <p className="text-sm text-gray-700">{s.quote}</p>
                <div className="flex items-center gap-2 mt-2">
                  <span className="text-xs text-blue-600">{s.source}</span>
                  <span className={`text-[10px] font-medium uppercase rounded px-1.5 py-0.5 ${RELEVANCE_CLASSES[s.relevance] || RELEVANCE_CLASSES.low}`}>
                    {s.relevance}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Key People */}
      {result.key_people && result.key_people.length > 0 && (
        <div className="px-5 py-4 border-b border-gray-100">
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Key Decision Makers</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {result.key_people.map((p, i) => (
              <div key={i} className="bg-gray-50 border border-gray-100 rounded-md p-3">
                <div className="font-medium text-sm text-gray-900">{p.name}</div>
                <div className="text-xs text-gray-500">{p.title}</div>
                {p.linkedin_url && (
                  <a href={p.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-xs text-blue-600 hover:text-blue-800 mt-1 block">
                    LinkedIn
                  </a>
                )}
                {p.context && <p className="text-xs text-gray-500 mt-1">{p.context}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Talking Points */}
      <div className="px-5 py-4 border-b border-gray-100">
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Talking Points</div>
        {result.talking_points && result.talking_points.length > 0 ? (
          <div className="space-y-2">
            {result.talking_points.map((tp, i) => (
              <div key={i} className="bg-blue-50 border border-blue-200 rounded-md p-3">
                <div className="text-xs font-bold text-blue-700 uppercase mb-1">{tp.hook_type.replace(/_/g, " ")}</div>
                <p className="text-sm text-gray-700 leading-relaxed">{tp.text}</p>
                <div className="text-xs text-gray-400 mt-1">Source: {tp.source_reference}</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-400 italic">No specific talking points identified. Review the evidence above for your own hooks.</p>
        )}
      </div>

      {/* Actions Bar */}
      <div className="bg-gray-50 border-t border-gray-100 px-5 py-4 flex flex-wrap gap-3">
        {result.talking_points && result.talking_points.length > 0 && (
          <button
            onClick={() => navigate("/queue")}
            className="bg-gray-900 text-white rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-gray-800 focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
          >
            Use Talking Points in Next Email
          </button>
        )}
        <button
          onClick={() => setShowConfirm(true)}
          className="bg-white border border-gray-200 text-gray-700 rounded-lg px-4 py-2.5 text-sm font-medium hover:bg-gray-50 focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
        >
          Re-run
        </button>
      </div>
      {showConfirm && (
        <div className="px-5 py-3 bg-gray-50 border-t border-gray-100">
          <p className="text-sm text-gray-700">Re-run deep research on <span className="font-medium">{companyName}</span>? ~$0.08</p>
          <div className="flex gap-2 mt-2">
            <button onClick={handleTrigger} className="bg-gray-900 text-white rounded px-3 py-1.5 text-sm font-medium hover:bg-gray-800">Run</button>
            <button onClick={() => setShowConfirm(false)} className="text-sm text-gray-500 px-3 py-1.5">Cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}
