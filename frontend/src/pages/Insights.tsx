import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import MetricCard from "../components/MetricCard";

const DEFAULT_CAMPAIGN = "Q1_2026_initial";

export default function Insights() {
  const metrics = useQuery({
    queryKey: ["campaign-metrics", DEFAULT_CAMPAIGN],
    queryFn: () => api.getCampaignMetrics(DEFAULT_CAMPAIGN),
  });

  const m = metrics.data?.metrics;
  const weekly = metrics.data?.weekly;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Insights</h1>
        <p className="text-gray-500 mt-1">Campaign performance and AI-powered analysis</p>
      </div>

      {/* AI Analysis placeholder */}
      <div className="bg-white rounded-lg border p-5 space-y-4">
        <h2 className="font-semibold text-gray-900">AI Analysis</h2>
        <p className="text-sm text-gray-500">
          Run an AI-powered analysis of campaign performance, template effectiveness,
          and receive actionable suggestions.
        </p>
        <button
          disabled
          className="px-4 py-2 bg-gray-200 text-gray-400 rounded-md text-sm font-medium cursor-not-allowed"
        >
          Run Analysis (Coming in Phase 4)
        </button>
      </div>

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
