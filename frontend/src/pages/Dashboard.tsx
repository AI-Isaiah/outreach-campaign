import { useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Inbox, ListTodo, Users, FileText, AlertTriangle } from "lucide-react";
import { api } from "../api/client";
import { getEmailConfig } from "../api/settings";
import type { StatsResponse, Campaign, PendingRepliesResponse, ReplyScanResponse, LinkedInScanResponse } from "../types";
import MetricCard from "../components/MetricCard";
import PendingReplyCard from "../components/PendingReplyCard";
import { SkeletonMetricCard, SkeletonCard } from "../components/Skeleton";
import EmptyState from "../components/EmptyState";
import ErrorCard from "../components/ui/ErrorCard";
import Card from "../components/ui/Card";
import Button from "../components/ui/Button";
import StatusBadge from "../components/StatusBadge";

export default function Dashboard() {
  const queryClient = useQueryClient();
  const stats = useQuery<StatsResponse>({ queryKey: ["stats"], queryFn: api.getStats });
  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.listCampaigns(),
  });
  const pendingReplies = useQuery<PendingRepliesResponse>({
    queryKey: ["pending-replies"],
    queryFn: api.listPendingReplies,
  });
  const scanReplies = useMutation<ReplyScanResponse, Error>({
    mutationFn: api.scanReplies,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pending-replies"] });
    },
  });
  const scanLinkedIn = useMutation<LinkedInScanResponse, Error>({
    mutationFn: api.scanLinkedInAcceptances,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });

  const emailConfig = useQuery({
    queryKey: ["email-config"],
    queryFn: getEmailConfig,
  });

  // F006: Reset scan mutations on unmount to prevent stale data on re-navigation
  useEffect(() => () => { scanReplies.reset(); scanLinkedIn.reset(); }, []);

  const replies = pendingReplies.data?.replies ?? [];
  const lastAutoScanAt = pendingReplies.data?.last_auto_scan_at ?? null;

  function formatAutoScanAge(isoDate: string | null): { text: string; color: string } {
    if (!isoDate) return { text: "Auto-scan not configured", color: "text-gray-400" };
    const diffMs = Date.now() - new Date(isoDate).getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 60) {
      return { text: `Auto-scanned ${diffMin} min ago`, color: "text-green-600" };
    }
    const diffHrs = Math.floor(diffMin / 60);
    return { text: `Last scan: ${diffHrs}h ago`, color: "text-amber-600" };
  }

  const autoScanBadge = formatAutoScanAge(lastAutoScanAt);

  const showDisconnectedBanner =
    emailConfig.data &&
    !emailConfig.data.gmail_connected &&
    emailConfig.data.gmail_email != null;

  const showNoSenderBanner =
    emailConfig.data &&
    !emailConfig.data.gmail_connected &&
    !emailConfig.data.smtp_configured;

  return (
    <div className="space-y-8">
      {/* Gmail disconnected banner */}
      {showDisconnectedBanner && (
        <div
          className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-center gap-3"
          role="alert"
        >
          <AlertTriangle size={18} className="text-red-600 flex-shrink-0" />
          <p className="text-sm text-red-800 flex-1">
            Gmail disconnected — reconnect in{" "}
            <Link to="/settings" className="font-medium underline hover:text-red-900">
              Settings
            </Link>{" "}
            to resume sending.
          </p>
        </div>
      )}

      {/* No sender configured banner */}
      {!showDisconnectedBanner && showNoSenderBanner && (
        <div
          className="bg-amber-50 border border-amber-200 rounded-lg p-4 flex items-center gap-3"
          role="alert"
        >
          <AlertTriangle size={18} className="text-amber-600 flex-shrink-0" />
          <p className="text-sm text-amber-800 flex-1">
            Set up email sending to start campaigns.{" "}
            <Link to="/settings" className="font-medium underline hover:text-amber-900">
              Go to Settings
            </Link>
          </p>
        </div>
      )}

      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-1">Overview of your outreach campaigns</p>
      </div>

      {/* Stats cards */}
      {stats.isLoading && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <SkeletonMetricCard key={i} />
          ))}
        </div>
      )}
      {stats.isError && (
        <ErrorCard
          message={(stats.error as Error).message}
          onRetry={() => stats.refetch()}
        />
      )}
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
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">
            Pending Replies
            {replies.length > 0 && (
              <span className="ml-2 text-sm font-normal text-gray-500">
                ({replies.length})
              </span>
            )}
          </h2>
          <div className="flex items-center gap-3">
            {pendingReplies.data && (
              <span className={`text-xs ${autoScanBadge.color}`}>
                {autoScanBadge.text}
              </span>
            )}
            <Button
              variant="accent"
              size="sm"
              onClick={() => scanReplies.mutate()}
              loading={scanReplies.isPending}
            >
              Scan for Replies
            </Button>
          </div>
        </div>

        {scanReplies.isError && (
          <div className="mb-3">
            <ErrorCard message={(scanReplies.error as Error).message} />
          </div>
        )}
        {scanReplies.data && (
          <p className="text-green-600 text-sm mb-3">
            Scanned {scanReplies.data.scanned} contacts, found {scanReplies.data.new_replies} new replies
          </p>
        )}

        {pendingReplies.isLoading && (
          <div className="space-y-3">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        )}

        {pendingReplies.isError && (
          <ErrorCard
            message={(pendingReplies.error as Error).message}
            onRetry={() => pendingReplies.refetch()}
          />
        )}

        {pendingReplies.data && replies.length > 0 && (
          <div className="space-y-3">
            {replies.slice(0, 5).map((reply) => (
              <PendingReplyCard key={reply.id} reply={reply} />
            ))}
            {replies.length > 5 && (
              <p className="text-sm text-gray-400 text-center">
                +{replies.length - 5} more pending replies
              </p>
            )}
          </div>
        )}

        {pendingReplies.data && replies.length === 0 && (
          <EmptyState
            icon={<Inbox size={40} />}
            title="All caught up"
            description="No replies waiting for review"
          />
        )}
      </div>

      {/* LinkedIn Sync */}
      <Card padding="md">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-900">LinkedIn Connections</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Scan Gmail for LinkedIn acceptance notifications and auto-advance sequences
            </p>
          </div>
          <Button
            variant="accent"
            size="md"
            onClick={() => scanLinkedIn.mutate()}
            loading={scanLinkedIn.isPending}
          >
            Sync LinkedIn
          </Button>
        </div>
        {scanLinkedIn.isError && (
          <div className="mt-3">
            <ErrorCard message={(scanLinkedIn.error as Error).message} />
          </div>
        )}
        {scanLinkedIn.data && (
          <div className="mt-3 space-y-2">
            <div className="flex gap-4 text-sm">
              <span className="text-gray-500">
                Scanned: <span className="font-medium text-gray-900">{scanLinkedIn.data.scanned}</span>
              </span>
              <span className="text-gray-500">
                Matched: <span className="font-medium text-green-600">{scanLinkedIn.data.matched}</span>
              </span>
              <span className="text-gray-500">
                Advanced: <span className="font-medium text-blue-600">{scanLinkedIn.data.advanced}</span>
              </span>
              {scanLinkedIn.data.already_processed > 0 && (
                <span className="text-gray-400">
                  Already processed: {scanLinkedIn.data.already_processed}
                </span>
              )}
            </div>
            {scanLinkedIn.data.details && scanLinkedIn.data.details.length > 0 && (
              <div className="border-t border-gray-100 pt-2 space-y-1">
                {scanLinkedIn.data.details.map((d, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className={`w-2 h-2 rounded-full ${d.advanced ? "bg-green-500" : "bg-gray-300"}`} />
                    <span className="text-gray-700">{d.contact_name}</span>
                    <span className="text-gray-400 text-xs">
                      via {d.match_method === "linkedin_url" ? "profile URL" : "name"}
                    </span>
                    {d.advanced && (
                      <span className="text-green-600 text-xs font-medium">sequence advanced</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Campaigns */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Campaigns</h2>
          <Link
            to="/campaigns"
            className="text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            View all
          </Link>
        </div>

        {campaigns.isLoading && (
          <div className="space-y-2">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        )}

        {campaigns.isError && (
          <ErrorCard
            message={(campaigns.error as Error).message}
            onRetry={() => campaigns.refetch()}
          />
        )}

        {campaigns.data && campaigns.data.length > 0 ? (
          <Card padding="none">
            <div className="divide-y divide-gray-100">
              {campaigns.data.map((c) => (
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
                  <StatusBadge status={c.status} />
                </Link>
              ))}
            </div>
          </Card>
        ) : (
          campaigns.data && (
            <EmptyState
              icon={<FileText size={40} />}
              title="No campaigns yet"
              description="Create your first campaign to start outreach"
            />
          )
        )}
      </div>

      {/* Quick actions */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">
          Quick Actions
        </h2>
        <div className="flex gap-3">
          <Link to="/queue">
            <Button variant="primary" size="lg" leftIcon={<ListTodo size={16} />}>
              Open Today's Queue
            </Button>
          </Link>
          <Link to="/contacts">
            <Button variant="secondary" size="lg" leftIcon={<Users size={16} />}>
              Browse Contacts
            </Button>
          </Link>
          <Link to="/templates">
            <Button variant="secondary" size="lg" leftIcon={<FileText size={16} />}>
              Manage Templates
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
