import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import StatusBadge from "../components/StatusBadge";

export default function CampaignList() {
  const { data, isLoading } = useQuery({
    queryKey: ["campaigns"],
    queryFn: api.listCampaigns,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Campaigns</h1>
        <p className="text-gray-500 mt-1">Manage your outreach campaigns</p>
      </div>

      {isLoading && <p className="text-gray-400">Loading...</p>}

      {data && data.length > 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
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
              {data.map((c: any) => (
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
        </div>
      ) : (
        !isLoading && <p className="text-gray-400">No campaigns found.</p>
      )}
    </div>
  );
}
