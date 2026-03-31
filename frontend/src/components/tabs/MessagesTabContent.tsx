import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MessageSquare } from "lucide-react";
import { campaignsApi } from "../../api/campaigns";
import type { CampaignMessage } from "../../types";
import { SkeletonTable } from "../Skeleton";

function ReplyBadge({ status }: { status: string }) {
  if (status === "replied_positive") {
    return <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500" title="Positive reply" />;
  }
  if (status === "replied_negative") {
    return <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-500" title="Negative reply" />;
  }
  return <span className="inline-block w-2.5 h-2.5 rounded-full bg-gray-300" title="No reply" />;
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  email_sent: "Email",
  linkedin_connect: "LinkedIn Connect",
  linkedin_message: "LinkedIn Message",
  linkedin_engage: "LinkedIn Engage",
  linkedin_insight: "LinkedIn Insight",
  linkedin_final: "LinkedIn Final",
};

export default function MessagesTabContent({ campaignId }: { campaignId: number }) {
  const [offset, setOffset] = useState(0);
  const { data, isLoading } = useQuery({
    queryKey: ["campaign-messages", campaignId, offset],
    queryFn: () => campaignsApi.getCampaignMessages(campaignId, { limit: 25, offset }),
  });

  if (isLoading) return <SkeletonTable rows={3} cols={5} />;

  const messages = data?.messages || [];
  const total = data?.total || 0;

  if (!messages.length) {
    return (
      <div className="text-center py-16">
        <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center mx-auto mb-4">
          <MessageSquare size={24} className="text-blue-500" />
        </div>
        <h3 className="text-lg font-semibold text-gray-900 mb-1">No messages sent yet</h3>
        <p className="text-sm text-gray-500">Queue and send to see history.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <table className="w-full">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr>
            <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Contact</th>
            <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Channel</th>
            <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Subject / Action</th>
            <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Sent</th>
            <th className="px-5 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Reply</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {messages.map((msg: CampaignMessage) => (
            <tr key={msg.id} className="hover:bg-gray-50 transition-colors">
              <td className="px-5 py-4 text-sm font-medium text-gray-900">{msg.contact_name}</td>
              <td className="px-5 py-4 text-sm text-gray-500">
                {EVENT_TYPE_LABELS[msg.event_type] ?? msg.event_type?.replace(/_/g, " ") ?? "\u2014"}
              </td>
              <td className="px-5 py-4 text-sm text-gray-500">{msg.template_subject || "\u2014"}</td>
              <td className="px-5 py-4 text-sm text-gray-500">{new Date(msg.sent_at).toLocaleDateString()}</td>
              <td className="px-5 py-4">
                <ReplyBadge status={msg.reply_status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {messages.length < total && (
        <div className="px-5 py-3 border-t border-gray-100 text-center">
          <button
            onClick={() => setOffset((prev) => prev + 25)}
            className="text-sm font-medium text-blue-600 hover:text-blue-700"
          >
            Load more ({messages.length} of {total})
          </button>
        </div>
      )}
    </div>
  );
}
