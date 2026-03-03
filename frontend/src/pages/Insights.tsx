import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import MetricCard from "../components/MetricCard";

const DEFAULT_CAMPAIGN = "Q1_2026_initial";

export default function Insights() {
  const queryClient = useQueryClient();
  const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(null);

  const metrics = useQuery({
    queryKey: ["campaign-metrics", DEFAULT_CAMPAIGN],
    queryFn: () => api.getCampaignMetrics(DEFAULT_CAMPAIGN),
  });

  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: api.listCampaigns,
  });

  const history = useQuery({
    queryKey: ["insight-history"],
    queryFn: api.getInsightHistory,
  });

  const analyze = useMutation({
    mutationFn: (campaignId: number) => api.runAnalysis(campaignId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insight-history"] });
    },
  });

  const m = metrics.data?.metrics;
  const weekly = metrics.data?.weekly;

  // Find the campaign ID for the default campaign
  const defaultCampaign = campaigns.data?.find(
    (c: any) => c.name === DEFAULT_CAMPAIGN
  );
  const campaignId = selectedCampaignId || defaultCampaign?.id;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Insights</h1>
        <p className="text-gray-500 mt-1">Campaign performance and AI-powered analysis</p>
      </div>

      {/* AI Analysis */}
      <div className="bg-white rounded-lg border p-5 space-y-4">
        <h2 className="font-semibold text-gray-900">AI Analysis</h2>
        <p className="text-sm text-gray-500">
          Run an AI-powered analysis of campaign performance, template effectiveness,
          and receive actionable suggestions.
        </p>
        <div className="flex items-center gap-3">
          {campaigns.data && campaigns.data.length > 0 && (
            <select
              value={campaignId || ""}
              onChange={(e) => setSelectedCampaignId(Number(e.target.value))}
              className="px-3 py-2 border rounded-md text-sm"
            >
              {campaigns.data.map((c: any) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
          <button
            onClick={() => campaignId && analyze.mutate(campaignId)}
            disabled={!campaignId || analyze.isPending}
            className="px-4 py-2 bg-gray-900 text-white rounded-md text-sm font-medium hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {analyze.isPending ? "Analyzing..." : "Run Analysis"}
          </button>
        </div>

        {analyze.isError && (
          <p className="text-red-500 text-sm">{(analyze.error as Error).message}</p>
        )}

        {analyze.data && (
          <div className="mt-4 space-y-3 border-t pt-4">
            <h3 className="text-sm font-semibold text-gray-700">Latest Analysis</h3>
            {analyze.data.insights?.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-gray-500 uppercase mb-1">Insights</h4>
                <ul className="list-disc list-inside space-y-1">
                  {analyze.data.insights.map((insight: string, i: number) => (
                    <li key={i} className="text-sm text-gray-700">{insight}</li>
                  ))}
                </ul>
              </div>
            )}
            {analyze.data.template_suggestions?.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-gray-500 uppercase mb-1">Template Suggestions</h4>
                <ul className="list-disc list-inside space-y-1">
                  {analyze.data.template_suggestions.map((s: string, i: number) => (
                    <li key={i} className="text-sm text-gray-700">{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {analyze.data.strategy_notes && (
              <div>
                <h4 className="text-xs font-medium text-gray-500 uppercase mb-1">Strategy Notes</h4>
                <p className="text-sm text-gray-700">{analyze.data.strategy_notes}</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Past Analysis Runs */}
      {history.data && history.data.length > 0 && (
        <div className="bg-white rounded-lg border p-5 space-y-3">
          <h2 className="font-semibold text-gray-900">Analysis History</h2>
          <div className="divide-y">
            {history.data.slice(0, 10).map((run: any) => (
              <div key={run.id} className="py-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">
                    Run #{run.id} — Campaign {run.campaign_id}
                  </span>
                  <span className="text-xs text-gray-400">{run.created_at}</span>
                </div>
                {run.insights_json && (() => {
                  try {
                    const parsed = JSON.parse(run.insights_json);
                    return parsed.insights ? (
                      <ul className="mt-1 list-disc list-inside">
                        {parsed.insights.slice(0, 3).map((i: string, idx: number) => (
                          <li key={idx} className="text-sm text-gray-600">{i}</li>
                        ))}
                      </ul>
                    ) : null;
                  } catch {
                    return null;
                  }
                })()}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Current metrics */}
      {m && (
        <>
          <div>
            <h2 className="text-lg font-semibold text-gray-900 mb-3">Campaign Metrics</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricCard label="Total Enrolled" value={m.total_enrolled} />
              <MetricCard label="Emails Sent" value={m.emails_sent} />
              <MetricCard
                label="Reply Rate"
                value={`${(m.reply_rate * 100).toFixed(1)}%`}
                accent="blue"
              />
              <MetricCard
                label="Positive Rate"
                value={`${(m.positive_rate * 100).toFixed(1)}%`}
                accent="green"
              />
              <MetricCard label="LinkedIn Connects" value={m.linkedin_connects} accent="blue" />
              <MetricCard label="LinkedIn Messages" value={m.linkedin_messages} accent="blue" />
              <MetricCard label="Calls Booked" value={m.calls_booked} accent="green" />
              <MetricCard label="Bounced" value={m.by_status.bounced || 0} accent="red" />
            </div>
          </div>

          {/* Status breakdown */}
          <div className="bg-white rounded-lg border p-5">
            <h2 className="font-semibold text-gray-900 mb-3">Status Breakdown</h2>
            <div className="space-y-2">
              {Object.entries(m.by_status).map(([status, count]) => (
                <div key={status} className="flex items-center justify-between">
                  <span className="text-sm text-gray-600 capitalize">
                    {status.replace(/_/g, " ")}
                  </span>
                  <div className="flex items-center gap-3">
                    <div className="w-32 bg-gray-100 rounded-full h-2">
                      <div
                        className="bg-blue-500 h-2 rounded-full"
                        style={{
                          width: `${m.total_enrolled > 0 ? ((count as number) / m.total_enrolled) * 100 : 0}%`,
                        }}
                      />
                    </div>
                    <span className="text-sm font-medium text-gray-700 w-8 text-right">
                      {count as number}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Weekly summary */}
      {weekly && (
        <div className="bg-white rounded-lg border p-5">
          <h2 className="font-semibold text-gray-900 mb-1">This Week</h2>
          <p className="text-xs text-gray-400 mb-3">{weekly.period}</p>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <div className="text-2xl font-bold text-gray-900">{weekly.emails_sent}</div>
              <div className="text-xs text-gray-500">Emails Sent</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-gray-900">{weekly.linkedin_actions}</div>
              <div className="text-xs text-gray-500">LinkedIn Actions</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-emerald-600">{weekly.replies_positive}</div>
              <div className="text-xs text-gray-500">Positive Replies</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
