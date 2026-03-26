import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle } from "lucide-react";
import { api } from "../../api/client";
import type { Campaign } from "../../types";

export default function BatchImportModal({
  jobId,
  qualifiedIds,
  onClose,
}: {
  jobId: number;
  qualifiedIds: number[];
  onClose: () => void;
}) {
  const [createDeals, setCreateDeals] = useState(true);
  const [campaignName, setCampaignName] = useState("");
  const queryClient = useQueryClient();

  const { data: campaigns } = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.listCampaigns(),
  });

  const batchMutation = useMutation({
    mutationFn: () =>
      api.batchImport(qualifiedIds, createDeals, campaignName || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["research-job", jobId] });
      // Auto-close after brief success display
      setTimeout(onClose, 2000);
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4">
        <div className="px-6 py-4 border-b border-gray-100">
          <h3 className="text-lg font-semibold text-gray-900">Import to CRM</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {qualifiedIds.length} qualified companies with discovered contacts
          </p>
        </div>

        {!batchMutation.isSuccess ? (
          <div className="px-6 py-5 space-y-4">
            <label className="flex items-center gap-3 rounded-lg border border-gray-200 p-3 cursor-pointer hover:bg-gray-50">
              <input
                type="checkbox"
                checked={createDeals}
                onChange={(e) => setCreateDeals(e.target.checked)}
                className="rounded border-gray-300 text-blue-600"
              />
              <div>
                <p className="text-sm font-medium text-gray-900">Create Pipeline Deals</p>
                <p className="text-xs text-gray-500">Add each company to your deal pipeline</p>
              </div>
            </label>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Enroll in Campaign</label>
              <select
                value={campaignName}
                onChange={(e) => setCampaignName(e.target.value)}
                className="w-full rounded-lg border border-gray-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Don't enroll (import only)</option>
                {(campaigns as Campaign[] || []).map((c) => (
                  <option key={c.id} value={c.name}>{c.name}</option>
                ))}
              </select>
            </div>
          </div>
        ) : (
          <div className="px-6 py-8 text-center space-y-3">
            <div className="w-14 h-14 rounded-full bg-green-50 flex items-center justify-center mx-auto">
              <CheckCircle size={28} className="text-green-600" />
            </div>
            <div>
              <p className="text-lg font-semibold text-gray-900">Import Complete</p>
              <div className="text-sm text-gray-600 mt-2 space-y-1">
                <p><strong>{batchMutation.data.imported_contacts}</strong> contacts imported</p>
                {batchMutation.data.deals_created > 0 && (
                  <p><strong>{batchMutation.data.deals_created}</strong> deals created</p>
                )}
                {batchMutation.data.enrolled > 0 && (
                  <p><strong>{batchMutation.data.enrolled}</strong> enrolled in campaign</p>
                )}
                {batchMutation.data.skipped_duplicates > 0 && (
                  <p className="text-gray-400">{batchMutation.data.skipped_duplicates} duplicates skipped</p>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-100">
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            {batchMutation.isSuccess ? "Done" : "Cancel"}
          </button>
          {!batchMutation.isSuccess && (
            <button
              onClick={() => batchMutation.mutate()}
              disabled={batchMutation.isPending}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {batchMutation.isPending ? "Importing..." : "Import Contacts"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
