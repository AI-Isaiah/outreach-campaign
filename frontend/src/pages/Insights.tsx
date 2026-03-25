import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Campaign, CampaignMetricsResponse, AnalysisResponse, DeferStatsResponse } from "../types";
import MetricCard from "../components/MetricCard";
import { SkeletonMetricCard, SkeletonCard } from "../components/Skeleton";
import ErrorCard from "../components/ui/ErrorCard";
import Card from "../components/ui/Card";
import Button from "../components/ui/Button";
import Select from "../components/ui/Select";
import { DEFAULT_CAMPAIGN } from "../constants";

export default function Insights() {
  const queryClient = useQueryClient();
  const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(null);

  const metrics = useQuery<CampaignMetricsResponse>({
    queryKey: ["campaign-metrics", DEFAULT_CAMPAIGN],
    queryFn: () => api.getCampaignMetrics(DEFAULT_CAMPAIGN),
  });

  const campaigns = useQuery<Campaign[]>({
    queryKey: ["campaigns"],
    queryFn: api.listCampaigns,
  });

  const history = useQuery<AnalysisResponse[]>({
    queryKey: ["insight-history"],
    queryFn: api.getInsightHistory,
  });

  const deferStats = useQuery<DeferStatsResponse>({
    queryKey: ["defer-stats"],
    queryFn: () => api.getDeferStats(),
  });

  const analyze = useMutation<AnalysisResponse, Error, number>({
    mutationFn: (campaignId: number) => api.runAnalysis(campaignId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insight-history"] });
    },
  });

  const m = metrics.data?.metrics;
  const weekly = metrics.data?.weekly;

  const defaultCampaign = campaigns.data?.find(
    (c: Campaign) => c.name === DEFAULT_CAMPAIGN
  );
  const campaignId = selectedCampaignId || defaultCampaign?.id;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Insights</h1>
        <p className="text-sm text-gray-500 mt-1">Campaign performance and AI-powered analysis</p>
      </div>

      {metrics.isLoading && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <SkeletonMetricCard key={i} />
          ))}
        </div>
      )}

      {metrics.isError && (
        <ErrorCard
          message={(metrics.error as Error).message}
          onRetry={() => metrics.refetch()}
        />
      )}

      {/* AI Analysis */}
      <Card>
        <h2 className="font-semibold text-gray-900 mb-1">AI Analysis</h2>
        <p className="text-sm text-gray-500 mb-4">
          Run an AI-powered analysis of campaign performance, template effectiveness,
          and receive actionable suggestions.
        </p>
        <div className="flex items-center gap-3">
          {campaigns.data && campaigns.data.length > 0 && (
            <Select
              value={campaignId || ""}
              onChange={(e) => setSelectedCampaignId(Number(e.target.value))}
            >
              {campaigns.data.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          )}
          <Button
            variant="primary"
            size="md"
            onClick={() => campaignId && analyze.mutate(campaignId)}
            disabled={!campaignId}
            loading={analyze.isPending}
          >
            Run Analysis
          </Button>
        </div>

        {analyze.isError && (
          <div className="mt-3">
            <ErrorCard message={(analyze.error as Error).message} />
          </div>
        )}

        {analyze.data && (
          <div className="mt-4 space-y-3 border-t border-gray-100 pt-4">
            <h3 className="text-sm font-semibold text-gray-700">Latest Analysis</h3>
            {analyze.data.insights?.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Insights</h4>
                <ul className="list-disc list-inside space-y-1">
                  {analyze.data.insights.map((insight, i) => (
                    <li key={i} className="text-sm text-gray-700">{insight}</li>
                  ))}
                </ul>
              </div>
            )}
            {analyze.data.template_suggestions?.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Template Suggestions</h4>
                <ul className="list-disc list-inside space-y-1">
                  {analyze.data.template_suggestions.map((s, i) => (
                    <li key={i} className="text-sm text-gray-700">{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {analyze.data.strategy_notes && (
              <div>
                <h4 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Strategy Notes</h4>
                <p className="text-sm text-gray-700">{analyze.data.strategy_notes}</p>
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Past Analysis Runs */}
      {history.data && history.data.length > 0 && (
        <Card>
          <h2 className="font-semibold text-gray-900 mb-3">Analysis History</h2>
          <div className="divide-y divide-gray-100">
            {history.data.slice(0, 10).map((run: AnalysisResponse) => (
              <div key={run.id} className="py-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-700">
                    Run #{run.id} — Campaign {run.campaign_id}
                  </span>
                  <span className="text-xs text-gray-400">{run.created_at}</span>
                </div>
                {run.insights_json && (() => {
                  try {
                    const parsed = JSON.parse(run.insights_json as string);
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
        </Card>
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
          <Card>
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
                        className="bg-blue-500 h-2 rounded-full transition-all"
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
          </Card>
        </>
      )}

      {/* Defer Analytics */}
      {deferStats.data && deferStats.data.total_count > 0 && (
        <Card>
          <h2 className="font-semibold text-gray-900 mb-4">Defer Analytics</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <MetricCard label="Skipped Today" value={deferStats.data.today_count} />
            <MetricCard label="Total Skipped" value={deferStats.data.total_count} />
            <MetricCard
              label="Top Reason"
              value={deferStats.data.by_reason?.[0]?.reason || "-"}
            />
          </div>

          {deferStats.data.by_reason?.length > 0 && (
            <div className="mt-4">
              <h3 className="text-sm font-medium text-gray-700 mb-2">Skip Reasons</h3>
              <div className="space-y-1.5">
                {deferStats.data.by_reason.map((r) => (
                  <div key={r.reason} className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">{r.reason}</span>
                    <span className="font-medium text-gray-700">{r.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {deferStats.data.repeat_deferrals?.length > 0 && (
            <div className="mt-4">
              <h3 className="text-sm font-medium text-gray-700 mb-2">
                Repeatedly Skipped Contacts
              </h3>
              <div className="space-y-1.5">
                {deferStats.data.repeat_deferrals.map((r) => (
                  <div key={r.contact_id} className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">{r.contact_name}</span>
                    <span className="font-medium text-amber-600">{r.defer_count}x skipped</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Weekly summary */}
      {weekly && (
        <Card>
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
        </Card>
      )}
    </div>
  );
}
