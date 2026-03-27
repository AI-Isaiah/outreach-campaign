import { useParams, Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { CompanyDetailResponse, Contact } from "../types";
import StatusBadge from "../components/StatusBadge";
import TagPicker from "../components/TagPicker";
import DeepResearchBrief from "../components/DeepResearchBrief";

export default function CompanyDetail() {
  const { id } = useParams<{ id: string }>();
  const companyId = Number(id);
  const navigate = useNavigate();

  const { data, isLoading, error } = useQuery<CompanyDetailResponse>({
    queryKey: ["company", companyId],
    queryFn: () => api.getCompany(companyId),
    enabled: !!id,
  });

  if (isLoading) return <p className="text-gray-400">Loading...</p>;
  if (error) return <p className="text-red-500">{(error as Error).message}</p>;
  if (!data) return null;

  const { company, contacts, event_count } = data;

  const aum = company.aum_millions
    ? company.aum_millions >= 1000
      ? `$${(company.aum_millions / 1000).toFixed(1)}B`
      : `$${company.aum_millions.toLocaleString()}M`
    : "-";

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <button onClick={() => navigate(-1)} className="text-sm text-gray-400 hover:text-gray-600">
          &larr; Back
        </button>
        <h1 className="text-2xl font-bold text-gray-900 mt-2">{company.name}</h1>
        {company.firm_type && (
          <p className="text-gray-500 mt-0.5">{company.firm_type}</p>
        )}
      </div>

      {/* Company info grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-lg border p-5">
          <div className="text-xs font-medium text-gray-500 uppercase mb-1">AUM</div>
          <div className="text-2xl font-bold text-gray-900">{aum}</div>
        </div>
        <div className="bg-white rounded-lg border p-5">
          <div className="text-xs font-medium text-gray-500 uppercase mb-1">Contacts</div>
          <div className="text-2xl font-bold text-gray-900">{contacts.length}</div>
        </div>
        <div className="bg-white rounded-lg border p-5">
          <div className="text-xs font-medium text-gray-500 uppercase mb-1">Activities</div>
          <div className="text-2xl font-bold text-gray-900">{event_count}</div>
        </div>
      </div>

      {/* Company details */}
      <div className="bg-white rounded-lg border p-5 space-y-2 text-sm">
        <h2 className="font-semibold text-gray-900 mb-3">Details</h2>
        {[
          ["Country", company.country],
          ["City", company.city],
          ["Website", company.website],
          ["LinkedIn", company.linkedin_url],
          ["GDPR", company.is_gdpr ? "Yes" : "No"],
        ].map(([label, value]) => (
          <div key={label as string} className="flex justify-between">
            <span className="text-gray-500">{label}</span>
            {(label === "Website" || label === "LinkedIn") && value ? (
              <a href={value as string} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-800 truncate max-w-xs">
                {(value as string).replace(/https?:\/\/(www\.)?/, "").slice(0, 40)}
              </a>
            ) : (
              <span>{(value as string) || "-"}</span>
            )}
          </div>
        ))}
      </div>

      {/* Deep Research */}
      <DeepResearchBrief companyId={companyId} companyName={company.name} />

      {/* Tags */}
      <div className="bg-white rounded-lg border p-5">
        <h2 className="font-semibold text-gray-900 mb-3">Tags</h2>
        <TagPicker entityType="company" entityId={companyId} />
      </div>

      {/* Contacts at this company */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="px-5 py-4 border-b">
          <h2 className="font-semibold text-gray-900">Contacts ({contacts.length})</h2>
        </div>
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b">
              <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">Title</th>
              <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">Email</th>
              <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
              <th className="text-center px-5 py-3 text-xs font-medium text-gray-500 uppercase">Rank</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {contacts.map((c: Contact) => (
              <tr key={c.id} className="hover:bg-gray-50">
                <td className="px-5 py-3">
                  <Link
                    to={`/contacts/${c.id}`}
                    className="font-medium text-blue-600 hover:text-blue-800"
                  >
                    {c.full_name || `${c.first_name || ""} ${c.last_name || ""}`.trim() || "-"}
                  </Link>
                </td>
                <td className="px-5 py-3 text-sm text-gray-600">{c.title || "-"}</td>
                <td className="px-5 py-3 text-sm text-gray-600">{c.email || "-"}</td>
                <td className="px-5 py-3">
                  {c.campaign_status ? <StatusBadge status={c.campaign_status} /> : <span className="text-gray-400 text-sm">-</span>}
                </td>
                <td className="px-5 py-3 text-center text-sm">{c.priority_rank}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
