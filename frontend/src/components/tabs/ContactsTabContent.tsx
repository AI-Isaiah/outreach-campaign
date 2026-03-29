import { useState, useMemo, useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { campaignsApi } from "../../api/campaigns";
import type { CampaignContact } from "../../api/campaigns";
import StatusBadge from "../StatusBadge";
import { SkeletonTable } from "../Skeleton";
import ErrorCard from "../ui/ErrorCard";
import { useToast } from "../Toast";
import { CHANNEL_LABELS } from "../../constants";
import { channelBadgeClass } from "../../utils/sequenceUtils";
import CrmContactPicker from "../../pages/campaigns/components/CrmContactPicker";

type Tab = "contacts" | "messages" | "sequence" | "analytics" | "queue";

const CONTACT_STATUS_FILTERS = [
  "", "queued", "in_progress", "replied_positive", "replied_negative",
  "no_response", "bounced", "completed", "unsubscribed",
] as const;

export default function ContactsTabContent({
  campaignName,
  campaignId,
  onSwitchTab,
}: {
  campaignName: string;
  campaignId: number;
  onSwitchTab: (tab: Tab) => void;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const filterParam = searchParams.get("filter") || "";
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [sortField, setSortField] = useState<string>("step");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [showAddContacts, setShowAddContacts] = useState(false);
  const [addContactIds, setAddContactIds] = useState<Set<number>>(new Set());
  const queryClient = useQueryClient();
  const { toast } = useToast();

  // Sync metric card filter from URL params
  useEffect(() => {
    if (filterParam === "contacted") setStatusFilter("no_response");
    else if (filterParam === "replied") setStatusFilter("replied_positive");
    else if (filterParam === "in_progress") setStatusFilter("in_progress");
    else if (filterParam) setStatusFilter(filterParam);
  }, [filterParam]);

  const { data, isLoading, isError, error, refetch } = useQuery<CampaignContact[]>({
    queryKey: ["campaign-contacts", campaignId, statusFilter],
    queryFn: () => campaignsApi.getCampaignContacts(campaignId, {
      status: statusFilter || undefined,
      sort: "step",
    }),
  });

  // Client-side sort
  const sortedData = useMemo(() => {
    if (!data) return [];
    const sorted = [...data].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "contact": cmp = (a.full_name || "").localeCompare(b.full_name || ""); break;
        case "company": cmp = (a.company_name || "").localeCompare(b.company_name || ""); break;
        case "step": cmp = a.current_step - b.current_step; break;
        case "status": cmp = a.status.localeCompare(b.status); break;
        default: cmp = 0;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [data, sortField, sortDir]);

  const toggleSort = (field: string) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("asc");
    }
  };

  if (isLoading) return <SkeletonTable rows={5} cols={5} />;
  if (isError) return <ErrorCard message={(error as Error).message} onRetry={() => refetch()} />;

  const SortHeader = ({ field, children }: { field: string; children: React.ReactNode }) => (
    <th
      className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide cursor-pointer hover:text-gray-700 select-none"
      onClick={() => toggleSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {sortField === field && (
          <span className="text-gray-400">{sortDir === "asc" ? "\u2191" : "\u2193"}</span>
        )}
      </span>
    </th>
  );

  return (
    <div className="space-y-4">
      {/* Filter + Add Contacts */}
      <div className="flex gap-2 flex-wrap items-center">
        {CONTACT_STATUS_FILTERS.map((s) => (
          <button
            key={s}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              statusFilter === s
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
            onClick={() => { setStatusFilter(s); setSearchParams({}, { replace: true }); }}
          >
            {s === "" ? "All" : s.replace(/_/g, " ")}
          </button>
        ))}
        <button
          onClick={() => setShowAddContacts(!showAddContacts)}
          className="ml-auto px-3 py-1 rounded-full text-xs font-medium bg-blue-600 text-white hover:bg-blue-700 transition-colors"
        >
          + Add Contacts
        </button>
      </div>

      {showAddContacts && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
          <div className="flex justify-between items-center">
            <h3 className="text-sm font-medium text-gray-900">Enroll contacts in this campaign</h3>
            <button onClick={() => setShowAddContacts(false)} className="text-gray-400 hover:text-gray-600 text-xs">Close</button>
          </div>
          <CrmContactPicker selectedIds={addContactIds} onSelectionChange={setAddContactIds} />
          {addContactIds.size > 0 && (
            <div className="flex items-center gap-3">
              <button
                onClick={async () => {
                  try {
                    await campaignsApi.enrollContacts(campaignId, Array.from(addContactIds));
                    queryClient.invalidateQueries({ queryKey: ["campaign-contacts", campaignId] });
                    queryClient.invalidateQueries({ queryKey: ["campaign-detail"] });
                    toast(`Enrolled ${addContactIds.size} contact${addContactIds.size !== 1 ? "s" : ""}`, "success");
                    setAddContactIds(new Set());
                    setShowAddContacts(false);
                  } catch (err: unknown) {
                    toast((err as Error).message || "Failed to enroll contacts", "error");
                  }
                }}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
              >
                Enroll {addContactIds.size} Contact{addContactIds.size !== 1 ? "s" : ""}
              </button>
              <span className="text-xs text-gray-500">{addContactIds.size} selected</span>
            </div>
          )}
        </div>
      )}

      {sortedData.length > 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <SortHeader field="contact">Contact</SortHeader>
                <SortHeader field="company">Company</SortHeader>
                <SortHeader field="step">Step</SortHeader>
                <SortHeader field="status">Status</SortHeader>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sortedData.map((c) => (
                <tr key={c.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-5 py-4">
                    <Link
                      to={`/contacts/${c.id}?campaign=${campaignName}`}
                      className="font-medium text-gray-900 hover:text-blue-600"
                    >
                      {c.full_name || `${c.first_name} ${c.last_name}`}
                    </Link>
                    {c.title && <p className="text-xs text-gray-400">{c.title}</p>}
                  </td>
                  <td className="px-5 py-4 text-sm text-gray-500">{c.company_name}</td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          onSwitchTab("queue");
                        }}
                        className={`text-xs font-medium px-2 py-0.5 rounded cursor-pointer hover:opacity-80 transition-opacity ${channelBadgeClass(c.current_channel || "")}`}
                        title={`View in queue`}
                      >
                        {CHANNEL_LABELS[c.current_channel || ""] ?? `Step ${c.current_step}`}
                      </button>
                      <span className="text-xs text-gray-400">{c.current_step}/{c.total_steps}</span>
                    </div>
                  </td>
                  <td className="px-5 py-4"><StatusBadge status={c.status} /></td>
                  <td className="px-5 py-4 flex gap-2">
                    <button
                      onClick={() => onSwitchTab("queue")}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      Queue
                    </button>
                    <Link
                      to={`/contacts/${c.id}?campaign=${campaignName}`}
                      className="text-xs text-gray-400 hover:underline"
                    >
                      Profile
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center py-12 text-sm text-gray-500">
          {statusFilter ? "No contacts with this status." : (
            <div className="space-y-3">
              <p>No contacts enrolled yet.</p>
              <button
                onClick={() => setShowAddContacts(true)}
                className="px-4 py-2 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors"
              >
                Add Contacts
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
