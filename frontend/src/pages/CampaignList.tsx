import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Megaphone, Plus } from "lucide-react";
import { api } from "../api/client";
import type { Campaign } from "../types";
import StatusBadge from "../components/StatusBadge";
import { SkeletonTable } from "../components/Skeleton";
import EmptyState from "../components/EmptyState";
import ErrorCard from "../components/ui/ErrorCard";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";

export default function CampaignList() {
  const { data, isLoading, isError, error, refetch } = useQuery<Campaign[]>({
    queryKey: ["campaigns"],
    queryFn: api.listCampaigns,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Campaigns</h1>
          <p className="text-sm text-gray-500 mt-1">Manage your outreach campaigns</p>
        </div>
        <Link to="/campaigns/new">
          <Button variant="primary" size="md" leftIcon={<Plus size={16} />}>
            Create Campaign
          </Button>
        </Link>
      </div>

      {isLoading && <SkeletonTable rows={4} cols={4} />}

      {isError && (
        <ErrorCard
          message={(error as Error).message}
          onRetry={() => refetch()}
        />
      )}

      {data && data.length > 0 ? (
        <Card padding="none">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Name
                </th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Description
                </th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Status
                </th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Created
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.map((c: Campaign) => (
                <tr key={c.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-5 py-4">
                    <Link
                      to={`/campaigns/${c.name}`}
                      className="font-medium text-blue-600 hover:text-blue-800"
                    >
                      {c.name}
                    </Link>
                  </td>
                  <td className="px-5 py-4 text-sm text-gray-500">
                    {c.description || "-"}
                  </td>
                  <td className="px-5 py-4">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="px-5 py-4 text-sm text-gray-500">
                    {c.created_at?.split("T")[0] || c.created_at?.split(" ")[0]}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : (
        !isLoading && !isError && (
          <EmptyState
            icon={<Megaphone size={40} />}
            title="No campaigns yet"
            description="Create your first campaign to start outreach"
          />
        )
      )}
    </div>
  );
}
