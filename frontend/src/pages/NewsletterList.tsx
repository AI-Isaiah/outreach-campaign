import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { NewsletterListResponse, Newsletter } from "../types";
import StatusBadge from "../components/StatusBadge";

export default function NewsletterList() {
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery<NewsletterListResponse>({
    queryKey: ["newsletters", page],
    queryFn: () => api.listNewsletters(page),
  });

  const newsletters = data?.newsletters || [];
  const totalPages = data?.pages || 1;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Newsletters</h1>
          <p className="text-gray-500 mt-1">
            {data?.total || 0} newsletters
          </p>
        </div>
        <Link
          to="/newsletters/new"
          className="px-4 py-2.5 bg-gray-900 text-white rounded-lg text-sm font-medium hover:bg-gray-800 transition-colors"
        >
          Compose Newsletter
        </Link>
      </div>

      {isLoading && <p className="text-gray-400">Loading...</p>}

      {newsletters.length > 0 ? (
        <>
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Subject
                  </th>
                  <th className="text-center px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Status
                  </th>
                  <th className="text-right px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Recipients
                  </th>
                  <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Sent
                  </th>
                  <th className="text-left px-5 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {newsletters.map((nl: Newsletter) => (
                  <tr key={nl.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-5 py-4">
                      <Link
                        to={`/newsletters/${nl.id}`}
                        className="font-medium text-blue-600 hover:text-blue-800"
                      >
                        {nl.subject}
                      </Link>
                    </td>
                    <td className="px-5 py-4 text-center">
                      <StatusBadge status={nl.status} />
                    </td>
                    <td className="px-5 py-4 text-right text-sm text-gray-600">
                      {nl.recipient_count || "-"}
                    </td>
                    <td className="px-5 py-4 text-sm text-gray-500">
                      {nl.sent_at ? new Date(nl.sent_at).toLocaleDateString() : "-"}
                    </td>
                    <td className="px-5 py-4 text-sm text-gray-500">
                      {new Date(nl.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-500">Page {page} of {totalPages}</p>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1.5 bg-white border border-gray-200 rounded-md text-sm disabled:opacity-50 hover:bg-gray-50"
                >
                  Previous
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="px-3 py-1.5 bg-white border border-gray-200 rounded-md text-sm disabled:opacity-50 hover:bg-gray-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      ) : (
        !isLoading && (
          <div className="text-center py-16 text-gray-400">
            <p className="text-lg mb-2">No newsletters yet</p>
            <p className="text-sm">Create your first newsletter to get started.</p>
          </div>
        )
      )}
    </div>
  );
}
