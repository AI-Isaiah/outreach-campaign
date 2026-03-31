import { useQuery } from "@tanstack/react-query";
import { Trophy } from "lucide-react";
import { api } from "../../api/client";
import type { CampaignMetricsResponse, TemplatePerformanceItem } from "../../types";
import { SkeletonTable } from "../Skeleton";
import ErrorCard from "../ui/ErrorCard";
import { channelBadgeClass } from "../../utils/sequenceUtils";

function ReplyBreakdownCard({ positive, negative }: { positive: number; negative: number }) {
  const total = positive + negative;

  if (total === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Reply Breakdown</h3>
        <p className="text-sm text-gray-400">No replies yet. Replies will appear as contacts respond.</p>
      </div>
    );
  }

  const positivePct = Math.round((positive / total) * 100);
  const negativePct = 100 - positivePct;

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5">
      <h3 className="text-sm font-semibold text-gray-900 mb-4">Reply Breakdown</h3>
      <div className="flex gap-6 mb-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-600 shrink-0" />
          <span className="text-2xl font-bold">{positive}</span>
          <span className="text-xs text-gray-500">Positive</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-red-600 shrink-0" />
          <span className="text-2xl font-bold">{negative}</span>
          <span className="text-xs text-gray-500">Negative</span>
        </div>
      </div>
      <div
        className="h-7 rounded-md overflow-hidden flex"
        role="img"
        aria-label={`Reply breakdown: ${positive} positive (${positivePct}%), ${negative} negative (${negativePct}%)`}
      >
        {positive > 0 && (
          <div
            className="bg-green-600 flex items-center justify-center text-white text-xs font-semibold min-w-[24px]"
            style={{ width: `${positivePct}%` }}
          >
            {positivePct >= 15 ? `${positivePct}%` : ""}
          </div>
        )}
        {negative > 0 && (
          <div
            className="bg-red-600 flex items-center justify-center text-white text-xs font-semibold min-w-[24px]"
            style={{ width: `${negativePct}%` }}
          >
            {negativePct >= 15 ? `${negativePct}%` : ""}
          </div>
        )}
      </div>
      {/* External labels for tiny segments */}
      {(positivePct > 0 && positivePct < 15) || (negativePct > 0 && negativePct < 15) ? (
        <div className="flex justify-between mt-1 text-xs text-gray-500">
          <span>{positivePct}% positive</span>
          <span>{negativePct}% negative</span>
        </div>
      ) : null}
    </div>
  );
}

function rateColorClass(rate: number): string {
  if (rate >= 0.5) return "text-green-600 font-semibold";
  if (rate >= 0.3) return "text-amber-600 font-semibold";
  return "text-red-600 font-semibold";
}

function TemplatePerformanceTable({
  data, isLoading, error, onRetry,
}: {
  data: TemplatePerformanceItem[];
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  if (isLoading) return <SkeletonTable rows={3} cols={5} />;
  if (error) return <ErrorCard message={error.message} onRetry={onRetry} />;
  if (!data || data.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Template Performance</h3>
        <p className="text-sm text-gray-400">No templates used yet.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden overflow-x-auto">
      <div className="px-5 py-4 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-900">Template Performance</h3>
      </div>
      <table className="w-full">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-200">
            <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Template</th>
            <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Channel</th>
            <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Sends</th>
            <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Rate</th>
            <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide hidden md:table-cell">Confidence</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {data.map((t) => {
            const resolved = t.positive + t.negative;
            const showRate = t.total_sends >= 10 && resolved > 0;
            return (
              <tr key={t.template_id} className="hover:bg-gray-50 transition-colors">
                <td className="px-5 py-4">
                  <span className="text-sm font-medium text-gray-900">{t.template_name}</span>
                  {t.is_winning && (
                    <span className="ml-2 inline-flex items-center gap-1 bg-green-100 text-green-800 px-2 py-0.5 rounded-full text-xs font-medium">
                      <Trophy size={12} />
                      Winning
                    </span>
                  )}
                </td>
                <td className="px-5 py-4">
                  <span className={`text-xs font-medium px-2 py-0.5 rounded ${channelBadgeClass(t.channel)}`}>
                    {t.channel === "email" ? "Email" : "LinkedIn"}
                  </span>
                </td>
                <td className="px-5 py-4 text-right text-sm text-gray-700">{t.total_sends}</td>
                <td className="px-5 py-4 text-right text-sm" aria-label={showRate ? `${(t.positive_rate * 100).toFixed(1)}% positive reply rate` : undefined}>
                  {showRate ? (
                    <span className={rateColorClass(t.positive_rate)}>
                      {(t.positive_rate * 100).toFixed(0)}%
                    </span>
                  ) : (
                    <span className="text-gray-400" title={resolved === 0 ? "Awaiting replies" : "Not enough sends"}>—</span>
                  )}
                </td>
                <td className="px-5 py-4 text-right text-sm text-gray-500 capitalize hidden md:table-cell">{t.confidence}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function AnalyticsTabContent({ metricsData, campaignName }: { metricsData: CampaignMetricsResponse; campaignName: string }) {
  const { metrics, variants, weekly } = metricsData;
  const bs = metrics?.by_status || {};
  const rb = metrics?.reply_breakdown;

  const { data: templatePerf, isLoading: tpLoading, error: tpError, refetch: tpRefetch } = useQuery<TemplatePerformanceItem[]>({
    queryKey: ["template-performance", campaignName],
    queryFn: () => api.getTemplatePerformance(campaignName),
    enabled: !!campaignName,
    staleTime: 60_000,
  });

  if (metrics.total_enrolled < 10) {
    return (
      <div className="text-center py-12 text-sm text-gray-500">
        Not enough data yet. Enroll 10+ contacts to see analytics.
      </div>
    );
  }

  const hasReplies = rb && rb.total > 0;
  const hasTemplateData = templatePerf && templatePerf.length > 0;
  const bothEmpty = !hasReplies && !tpLoading && !hasTemplateData;

  return (
    <div className="space-y-6">
      {/* Status breakdown */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Status Breakdown</h3>
        <div className="grid grid-cols-3 md:grid-cols-6 gap-4 text-center">
          {Object.entries(bs).map(([status, count]) => (
            <div key={status}>
              <p className="text-2xl font-bold">{count as number}</p>
              <p className="text-xs text-gray-500 capitalize">{status.replace(/_/g, " ")}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Reply breakdown */}
      {bothEmpty ? (
        <div className="text-center py-8 text-sm text-gray-400">
          Outreach is running — replies and template insights will appear here as contacts respond.
        </div>
      ) : (
        <>
          <ReplyBreakdownCard positive={rb?.positive ?? 0} negative={rb?.negative ?? 0} />

          {/* Weekly summary */}
          {weekly && (
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-gray-900 mb-1">This Week</h3>
              <p className="text-xs text-gray-400 mb-4">{weekly.period}</p>
              <div className="grid grid-cols-3 md:grid-cols-5 gap-4 text-center">
                <div>
                  <p className="text-xl font-bold">{weekly.emails_sent}</p>
                  <p className="text-xs text-gray-500">Emails</p>
                </div>
                <div>
                  <p className="text-xl font-bold">{weekly.linkedin_actions}</p>
                  <p className="text-xs text-gray-500">LinkedIn</p>
                </div>
                <div>
                  <p className="text-xl font-bold text-green-600">{weekly.replies_positive}</p>
                  <p className="text-xs text-gray-500">Positive</p>
                </div>
                <div>
                  <p className="text-xl font-bold text-red-500">{weekly.replies_negative}</p>
                  <p className="text-xs text-gray-500">Negative</p>
                </div>
                <div>
                  <p className="text-xl font-bold text-blue-600">{weekly.calls_booked}</p>
                  <p className="text-xs text-gray-500">Calls</p>
                </div>
              </div>
            </div>
          )}

          {/* Template performance */}
          <TemplatePerformanceTable data={templatePerf ?? []} isLoading={tpLoading} error={tpError} onRetry={() => tpRefetch()} />
        </>
      )}

      {/* A/B Variants */}
      {(variants || []).length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h3 className="text-sm font-semibold text-gray-900">A/B Variant Comparison</h3>
          </div>
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">Variant</th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">Total</th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">Reply Rate</th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">Positive Rate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {variants.map((v) => (
                <tr key={v.variant}>
                  <td className="px-5 py-3 font-medium">{v.variant}</td>
                  <td className="px-5 py-3 text-right">{v.total}</td>
                  <td className="px-5 py-3 text-right">{(v.reply_rate * 100).toFixed(1)}%</td>
                  <td className="px-5 py-3 text-right">{(v.positive_rate * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
