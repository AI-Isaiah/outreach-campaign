import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import MetricCard from "../components/MetricCard";
import PendingReplyCard from "../components/PendingReplyCard";

export default function Dashboard() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.getStats });
  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: api.listCampaigns,
  });
  const pendingReplies = useQuery({
    queryKey: ["pending-replies"],
    queryFn: api.listPendingReplies,
  });

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-500 mt-1">Overview of your outreach campaigns</p>
      </div>

      {/* Stats cards */}
      {stats.data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label="Companies" value={stats.data.companies} />
          <MetricCard label="Contacts" value={stats.data.contacts} />
          <MetricCard
            label="Verified Emails"
            value={stats.data.email_status.verified}
            accent="green"
          />
          <MetricCard
            label="With LinkedIn"
            value={stats.data.with_linkedin}
            accent="blue"
          />
          <MetricCard label="Campaigns" value={stats.data.campaigns} />
          <MetricCard label="Enrolled" value={stats.data.enrolled} />
          <MetricCard label="Events Logged" value={stats.data.events} />
          <MetricCard
            label="GDPR Contacts"
            value={stats.data.gdpr}
            accent="yellow"
          />
        </div>
      )}

      {/* Pending Replies */}
      {pendingReplies.data && pendingReplies.data.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-900">
              Pending Replies ({pendingReplies.data.length})
            </h2>
          </div>
          <div className="space-y-3">
            {pendingReplies.data.slice(0, 5).map((reply: any) => (
              <PendingReplyCard key={reply.id} reply={reply} />
            ))}
            {pendingReplies.data.length > 5 && (
              <p className="text-sm text-gray-400 text-center">
                +{pendingReplies.data.length - 5} more pending replies
              </p>
            )}
          </div>
        </div>
      )}

      {/* Campaigns */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Campaigns</h2>
          <Link
            to="/campaigns"
            className="text-sm text-blue-600 hover:text-blue-800"
          >
            View all
          </Link>
        </div>
        {campaigns.data && campaigns.data.length > 0 ? (
          <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
            {campaigns.data.map((c: any) => (
              <Link
                key={c.id}
                to={`/campaigns/${c.name}`}
                className="flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors"
              >
                <div>
                  <span className="font-medium text-gray-900">{c.name}</span>
                  {c.description && (
                    <span className="text-gray-400 ml-2 text-sm">
                      {c.description}
                    </span>
                  )}
                </div>
                <span
                  className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                    c.status === "active"
                      ? "bg-green-100 text-green-800"
                      : "bg-gray-100 text-gray-600"
                  }`}
                >
                  {c.status}
                </span>
              </Link>
            ))}
          </div>
        ) : campaigns.isLoading ? (
          <p className="text-gray-400">Loading...</p>
        ) : (
          <p className="text-gray-400">No campaigns found.</p>
        )}
      </div>

      {/* Quick actions */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">
          Quick Actions
        </h2>
        <div className="flex gap-3">
          <Link
            to="/queue"
            className="px-4 py-2.5 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors"
          >
            Open Today's Queue
          </Link>
          <Link
            to="/contacts"
            className="px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
          >
            Browse Contacts
          </Link>
          <Link
            to="/templates"
            className="px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
          >
            Manage Templates
          </Link>
        </div>
      </div>
    </div>
  );
}
