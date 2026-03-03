import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import MetricCard from "../components/MetricCard";
import StatusBadge from "../components/StatusBadge";

export default function CampaignDetail() {
  const { name } = useParams<{ name: string }>();
  const { data, isLoading, error } = useQuery({
    queryKey: ["campaign-metrics", name],
    queryFn: () => api.getCampaignMetrics(name!),
    enabled: !!name,
  });

  if (isLoading) return <p className="text-gray-400">Loading...</p>;
  if (error)
    return (
      <p className="text-red-500">{(error as Error).message}</p>
    );
  if (!data) return null;

  const { campaign, metrics, variants, weekly, firm_breakdown } = data;
  const bs = metrics.by_status;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {campaign.name}
          </h1>
          {campaign.description && (
            <p className="text-gray-500 mt-1">{campaign.description}</p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={campaign.status} />
          <Link
            to={`/queue`}
            className="px-3 py-1.5 bg-gray-900 text-white rounded-md text-sm font-medium hover:bg-gray-800 transition-colors"
          >
            Open Queue
          </Link>
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Total Enrolled" value={metrics.total_enrolled} />
        <MetricCard
          label="Reply Rate"
          value={`${(metrics.reply_rate * 100).toFixed(1)}%`}
          accent="green"
        />
        <MetricCard
          label="Positive Rate"
          value={`${(metrics.positive_rate * 100).toFixed(1)}%`}
          accent="green"
        />
        <MetricCard
          label="Calls Booked"
          value={metrics.calls_booked}
          accent="blue"
        />
      </div>

      {/* Status breakdown */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">
          Status Breakdown
        </h2>
        <div className="grid grid-cols-3 md:grid-cols-6 gap-4 text-center">
          {Object.entries(bs).map(([status, count]) => (
            <div key={status}>
              <p className="text-2xl font-bold">{count as number}</p>
              <p className="text-xs text-gray-500 capitalize">
                {status.replace(/_/g, " ")}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Activity counts */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Emails Sent" value={metrics.emails_sent} />
        <MetricCard
          label="LinkedIn Connects"
          value={metrics.linkedin_connects}
          accent="blue"
        />
        <MetricCard
          label="LinkedIn Messages"
          value={metrics.linkedin_messages}
          accent="blue"
        />
        <MetricCard
          label="Calls Booked"
          value={metrics.calls_booked}
          accent="green"
        />
      </div>

      {/* This Week */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-lg font-semibold text-gray-900 mb-1">
          This Week
        </h2>
        <p className="text-sm text-gray-400 mb-4">{weekly.period}</p>
        <div className="grid grid-cols-3 md:grid-cols-6 gap-4 text-center">
          <div>
            <p className="text-xl font-bold">{weekly.emails_sent}</p>
            <p className="text-xs text-gray-500">Emails</p>
          </div>
          <div>
            <p className="text-xl font-bold">{weekly.linkedin_actions}</p>
            <p className="text-xs text-gray-500">LinkedIn</p>
          </div>
          <div>
            <p className="text-xl font-bold text-green-600">
              {weekly.replies_positive}
            </p>
            <p className="text-xs text-gray-500">Positive</p>
          </div>
          <div>
            <p className="text-xl font-bold text-red-500">
              {weekly.replies_negative}
            </p>
            <p className="text-xs text-gray-500">Negative</p>
          </div>
          <div>
            <p className="text-xl font-bold text-blue-600">
              {weekly.calls_booked}
            </p>
            <p className="text-xs text-gray-500">Calls</p>
          </div>
          <div>
            <p className="text-xl font-bold">{weekly.new_no_response}</p>
            <p className="text-xs text-gray-500">No Response</p>
          </div>
        </div>
      </div>

      {/* A/B Variant Comparison */}
      {variants.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-lg font-semibold text-gray-900">
              A/B Variant Comparison
            </h2>
          </div>
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Variant
                </th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Total
                </th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Positive
                </th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Negative
                </th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Reply Rate
                </th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Positive Rate
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {variants.map((v: any) => (
                <tr key={v.variant}>
                  <td className="px-5 py-3 font-medium">{v.variant}</td>
                  <td className="px-5 py-3 text-right">{v.total}</td>
                  <td className="px-5 py-3 text-right text-green-600">
                    {v.replied_positive}
                  </td>
                  <td className="px-5 py-3 text-right text-red-500">
                    {v.replied_negative}
                  </td>
                  <td className="px-5 py-3 text-right">
                    {(v.reply_rate * 100).toFixed(1)}%
                  </td>
                  <td className="px-5 py-3 text-right">
                    {(v.positive_rate * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Firm Type Breakdown */}
      {firm_breakdown.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-lg font-semibold text-gray-900">
              Reply Rate by Firm Type
            </h2>
          </div>
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Firm Type
                </th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Total
                </th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Positive
                </th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Negative
                </th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Reply Rate
                </th>
                <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Positive Rate
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {firm_breakdown.map((f: any) => (
                <tr key={f.firm_type}>
                  <td className="px-5 py-3 font-medium">{f.firm_type}</td>
                  <td className="px-5 py-3 text-right">{f.total}</td>
                  <td className="px-5 py-3 text-right text-green-600">
                    {f.replied_positive}
                  </td>
                  <td className="px-5 py-3 text-right text-red-500">
                    {f.replied_negative}
                  </td>
                  <td className="px-5 py-3 text-right">
                    {(f.reply_rate * 100).toFixed(1)}%
                  </td>
                  <td className="px-5 py-3 text-right">
                    {(f.positive_rate * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
