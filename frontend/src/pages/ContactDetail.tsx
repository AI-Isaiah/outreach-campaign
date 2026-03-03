import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import UnifiedTimeline from "../components/UnifiedTimeline";

export default function ContactDetail() {
  const { id } = useParams<{ id: string }>();
  const contactId = Number(id);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["contact", contactId],
    queryFn: () => api.getContact(contactId),
    enabled: !!id,
  });

  const [statusForm, setStatusForm] = useState({
    campaign: "",
    newStatus: "replied_positive",
    note: "",
  });

  const [phoneInput, setPhoneInput] = useState("");

  const statusMutation = useMutation({
    mutationFn: () =>
      api.updateContactStatus(
        contactId,
        statusForm.campaign,
        statusForm.newStatus,
        statusForm.note || undefined,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contact", contactId] });
      queryClient.invalidateQueries({ queryKey: ["timeline", contactId] });
      setStatusForm((s) => ({ ...s, note: "" }));
    },
  });

  const phoneMutation = useMutation({
    mutationFn: () => api.updatePhone(contactId, phoneInput),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contact", contactId] });
      setPhoneInput("");
    },
  });

  if (isLoading) return <p className="text-gray-400">Loading...</p>;
  if (error)
    return <p className="text-red-500">{(error as Error).message}</p>;
  if (!data) return null;

  const { contact, enrollments, notes } = data;

  // Set default campaign from first enrollment
  if (!statusForm.campaign && enrollments.length > 0) {
    statusForm.campaign = enrollments[0].campaign_name;
  }

  const displayName =
    contact.full_name ||
    `${contact.first_name || ""} ${contact.last_name || ""}`.trim() ||
    contact.email ||
    `Contact #${contact.id}`;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <Link
          to="/contacts"
          className="text-sm text-gray-400 hover:text-gray-600"
        >
          &larr; Contacts
        </Link>
        <h1 className="text-2xl font-bold text-gray-900 mt-2">
          {displayName}
        </h1>
        {contact.title && (
          <p className="text-gray-500 mt-0.5">{contact.title}</p>
        )}
      </div>

      {/* Contact info */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-3">
          <h2 className="font-semibold text-gray-900">Contact Info</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">Email</span>
              <span>{contact.email || "-"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Email Status</span>
              <StatusBadge status={contact.email_status} />
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">LinkedIn</span>
              {contact.linkedin_url ? (
                <a
                  href={contact.linkedin_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:text-blue-800 truncate max-w-xs"
                >
                  Profile
                </a>
              ) : (
                <span>-</span>
              )}
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-500">Phone</span>
              {contact.phone_number ? (
                <span>{contact.phone_number}</span>
              ) : (
                <div className="flex gap-1">
                  <input
                    type="text"
                    value={phoneInput}
                    onChange={(e) => setPhoneInput(e.target.value)}
                    placeholder="+1 555 123 4567"
                    className="w-36 px-2 py-1 border rounded text-xs"
                  />
                  <button
                    onClick={() => phoneMutation.mutate()}
                    disabled={!phoneInput || phoneMutation.isPending}
                    className="px-2 py-1 bg-gray-800 text-white rounded text-xs disabled:opacity-50"
                  >
                    Add
                  </button>
                </div>
              )}
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Priority Rank</span>
              <span>{contact.priority_rank}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">GDPR</span>
              <span>
                {contact.is_gdpr ? (
                  <span className="text-red-500">Yes</span>
                ) : (
                  "No"
                )}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Unsubscribed</span>
              <span>
                {contact.unsubscribed ? (
                  <span className="text-red-500">Yes</span>
                ) : (
                  "No"
                )}
              </span>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-3">
          <h2 className="font-semibold text-gray-900">Company</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">Company</span>
              {contact.company_id ? (
                <Link
                  to={`/companies/${contact.company_id}`}
                  className="font-medium text-blue-600 hover:text-blue-800"
                >
                  {contact.company_name || "-"}
                </Link>
              ) : (
                <span className="font-medium">{contact.company_name || "-"}</span>
              )}
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">AUM</span>
              <span>
                {contact.aum_millions
                  ? `$${contact.aum_millions.toLocaleString()}M`
                  : "-"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Firm Type</span>
              <span>{contact.firm_type || "-"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Country</span>
              <span>{contact.country || "-"}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Campaign Enrollments */}
      {enrollments.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="font-semibold text-gray-900">
              Campaign Enrollments
            </h2>
          </div>
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Campaign
                </th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Status
                </th>
                <th className="text-center px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Step
                </th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Next Action
                </th>
                <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">
                  Variant
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {enrollments.map((e: any) => (
                <tr key={e.id}>
                  <td className="px-5 py-3">
                    <Link
                      to={`/campaigns/${e.campaign_name}`}
                      className="text-blue-600 hover:text-blue-800 font-medium"
                    >
                      {e.campaign_name}
                    </Link>
                  </td>
                  <td className="px-5 py-3">
                    <StatusBadge status={e.status} />
                  </td>
                  <td className="px-5 py-3 text-center">{e.current_step}</td>
                  <td className="px-5 py-3 text-sm text-gray-500">
                    {e.next_action_date || "-"}
                  </td>
                  <td className="px-5 py-3 text-sm text-gray-500">
                    {e.assigned_variant || "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Log Response */}
      {enrollments.some(
        (e: any) =>
          e.status === "queued" || e.status === "in_progress",
      ) && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-900 mb-4">Log Response</h2>
          <div className="space-y-3">
            <div className="flex gap-3">
              <select
                value={statusForm.campaign}
                onChange={(e) =>
                  setStatusForm((s) => ({ ...s, campaign: e.target.value }))
                }
                className="px-3 py-2 border border-gray-200 rounded-md text-sm bg-white"
              >
                {enrollments
                  .filter(
                    (e: any) =>
                      e.status === "queued" || e.status === "in_progress",
                  )
                  .map((e: any) => (
                    <option key={e.campaign_name} value={e.campaign_name}>
                      {e.campaign_name}
                    </option>
                  ))}
              </select>
              <select
                value={statusForm.newStatus}
                onChange={(e) =>
                  setStatusForm((s) => ({ ...s, newStatus: e.target.value }))
                }
                className="px-3 py-2 border border-gray-200 rounded-md text-sm bg-white"
              >
                <option value="replied_positive">Positive Reply</option>
                <option value="replied_negative">Negative Reply</option>
                <option value="no_response">No Response</option>
                <option value="bounced">Bounced</option>
              </select>
            </div>
            <textarea
              placeholder="Optional note (e.g., call booked for Tuesday, interested in factsheet...)"
              value={statusForm.note}
              onChange={(e) =>
                setStatusForm((s) => ({ ...s, note: e.target.value }))
              }
              className="w-full h-20 px-3 py-2 border border-gray-200 rounded-md text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <div className="flex gap-2">
              <button
                onClick={() => statusMutation.mutate()}
                disabled={statusMutation.isPending}
                className="px-4 py-2 bg-gray-900 text-white rounded-md text-sm font-medium hover:bg-gray-800 disabled:opacity-50 transition-colors"
              >
                {statusMutation.isPending ? "Saving..." : "Log Response"}
              </button>
              {statusMutation.isError && (
                <span className="text-red-500 text-sm self-center">
                  {(statusMutation.error as Error).message}
                </span>
              )}
              {statusMutation.isSuccess && (
                <span className="text-green-600 text-sm self-center">
                  Saved
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Notes */}
      {notes.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-900 mb-4">Notes</h2>
          <div className="space-y-3">
            {notes.map((n: any) => (
              <div key={n.id} className="bg-gray-50 rounded-md p-3">
                <div className="flex justify-between mb-1">
                  <span className="text-xs font-medium text-gray-500 capitalize">
                    {n.note_type.replace(/_/g, " ")}
                  </span>
                  <span className="text-xs text-gray-400">
                    {n.created_at}
                  </span>
                </div>
                <p className="text-sm text-gray-700">{n.content}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Unified Timeline */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="font-semibold text-gray-900 mb-4">Interaction Timeline</h2>
        <UnifiedTimeline contactId={contactId} />
      </div>
    </div>
  );
}
